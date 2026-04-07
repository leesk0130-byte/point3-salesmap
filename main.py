"""
Point3 CRM - Flask 백엔드 서버
"""

import os
import json
import re
import uuid
import csv
import io
import hashlib
from datetime import datetime
from urllib.parse import quote
from functools import wraps

from flask import Flask, request, jsonify, render_template, Response, send_file, redirect, session
from flask_cors import CORS
import requests
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# ── Flask 앱 초기화 ──
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.secret_key = os.environ.get("SECRET_KEY", "point3-crm-2026-secret")
CORS(app)

# ── 최고 관리자 설정 ──
SUPERADMIN_USERNAME = "leesk0130"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "734818849350-qlm4r3mlbksfrv41hm38l78vscu29biu.apps.googleusercontent.com")

# ── Firestore 설정 ──
FIREBASE_PROJECT_ID = "point3-salesmap99"
FIRESTORE_BASE = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"
FIREBASE_API_KEY = "AIzaSyA7u_44ljLdf5yxyihKO0qU51DkMZyiV_w"

# 로컬 폴백용 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)


# ══════════════════════════════════════════
#  Firestore 헬퍼 함수
# ══════════════════════════════════════════

def _fs_to_dict(fields):
    """Firestore 필드 → 파이썬 dict 변환"""
    result = {}
    for k, v in fields.items():
        if not v or not isinstance(v, dict):
            result[k] = None
        elif "stringValue" in v:
            result[k] = v["stringValue"]
        elif "booleanValue" in v:
            result[k] = v["booleanValue"]
        elif "integerValue" in v:
            result[k] = int(v["integerValue"])
        elif "doubleValue" in v:
            result[k] = v["doubleValue"]
        elif "nullValue" in v:
            result[k] = None
        elif "arrayValue" in v:
            values = v["arrayValue"].get("values", [])
            result[k] = [_fs_to_dict(item.get("mapValue", {}).get("fields", {})) if "mapValue" in item else
                         item.get("stringValue", item.get("booleanValue", item.get("integerValue", "")))
                         for item in values]
        elif "mapValue" in v:
            result[k] = _fs_to_dict(v["mapValue"].get("fields", {}))
        else:
            result[k] = None
    return result


def _dict_to_fs(d):
    """파이썬 dict → Firestore 필드 변환"""
    fields = {}
    for k, v in d.items():
        if isinstance(v, bool):
            fields[k] = {"booleanValue": v}
        elif isinstance(v, int):
            fields[k] = {"integerValue": str(v)}
        elif isinstance(v, float):
            fields[k] = {"doubleValue": v}
        elif isinstance(v, str):
            fields[k] = {"stringValue": v}
        elif isinstance(v, list):
            values = []
            for item in v:
                if isinstance(item, dict):
                    values.append({"mapValue": {"fields": _dict_to_fs(item)}})
                elif isinstance(item, str):
                    values.append({"stringValue": item})
                else:
                    values.append({"stringValue": str(item)})
            fields[k] = {"arrayValue": {"values": values} if values else {"values": []}}
        elif v is None:
            fields[k] = {"nullValue": None}
        elif isinstance(v, dict):
            fields[k] = {"mapValue": {"fields": _dict_to_fs(v)}}
        else:
            fields[k] = {"stringValue": str(v)}
    return fields


def fs_get_collection(collection):
    """Firestore 컬렉션의 모든 문서 가져오기"""
    try:
        url = f"{FIRESTORE_BASE}/{collection}?key={FIREBASE_API_KEY}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            docs = data.get("documents", [])
            return [_fs_to_dict(doc.get("fields", {})) for doc in docs]
        return []
    except Exception as e:
        print(f"[Firestore GET 오류] {collection}: {e}")
        return []


def fs_set_doc(collection, doc_id, data_dict):
    """Firestore 문서 생성/덮어쓰기"""
    try:
        url = f"{FIRESTORE_BASE}/{collection}/{doc_id}?key={FIREBASE_API_KEY}"
        body = {"fields": _dict_to_fs(data_dict)}
        resp = requests.patch(url, json=body, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"[Firestore SET 오류] {collection}/{doc_id}: {e}")
        return False


def fs_delete_doc(collection, doc_id):
    """Firestore 문서 삭제"""
    try:
        url = f"{FIRESTORE_BASE}/{collection}/{doc_id}?key={FIREBASE_API_KEY}"
        resp = requests.delete(url, timeout=10)
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[Firestore DEL 오류] {collection}/{doc_id}: {e}")
        return False


# ══════════════════════════════════════════
#  데이터 함수 (Firestore 기반)
# ══════════════════════════════════════════

def load_stores():
    return fs_get_collection("stores")

def save_store(store):
    fs_set_doc("stores", store["id"], store)

def save_stores(stores):
    for s in stores:
        fs_set_doc("stores", s["id"], s)

def delete_store_doc(store_id):
    fs_delete_doc("stores", store_id)

def load_users():
    return fs_get_collection("users")

def save_user(user):
    fs_set_doc("users", user["id"], user)

def save_users(users):
    for u in users:
        fs_set_doc("users", u["id"], u)


# ══════════════════════════════════════════
#  인증 시스템
# ══════════════════════════════════════════

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def get_current_user():
    """세션에서 현재 로그인 유저 반환. 없으면 None"""
    uid = session.get("user_id")
    if not uid:
        return None
    users = load_users()
    for u in users:
        if u["id"] == uid:
            return u
    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "로그인이 필요합니다."}), 401
            return redirect("/login")
        # 팀 미설정 → 팀 설정 페이지로
        if not user.get("teamName") and request.path not in ("/team-setup", "/auth/set-team", "/auth/logout"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "팀 설정이 필요합니다."}), 403
            return redirect("/team-setup")
        # 미승인 → 대기 페이지로
        if not user.get("isApproved") and request.path not in ("/pending", "/auth/me", "/auth/logout"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "승인 대기 중입니다."}), 403
            return redirect("/pending")
        return f(*args, **kwargs)
    return decorated


def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user.get("role") != "superadmin":
            return jsonify({"error": "권한이 없습니다."}), 403
        return f(*args, **kwargs)
    return decorated


# ── 초기 관리자 계정 자동 생성 ──
def ensure_superadmin():
    users = load_users()
    for u in users:
        if u["username"] == SUPERADMIN_USERNAME:
            return
    admin = {
        "id": str(uuid.uuid4()),
        "username": SUPERADMIN_USERNAME,
        "password": hash_pw("12345"),
        "name": "관리자",
        "teamName": "point3",
        "isApproved": True,
        "role": "superadmin",
        "created_at": datetime.now().isoformat(),
    }
    users.append(admin)
    save_users(users)
    # 기존 매장에 teamName 할당
    stores = load_stores()
    changed = False
    for s in stores:
        if not s.get("teamName"):
            s["teamName"] = "Point3"
            changed = True
    if changed:
        save_stores(stores)



def extract_district(address):
    """주소에서 '구' 이름 추출 (예: '강남구'). 없으면 '기타' 반환"""
    match = re.search(r'\S+구', address)
    return match.group(0) if match else "기타"


def get_last_visit(store):
    """매장의 최근 방문일과 결과를 반환"""
    visits = store.get("visits", [])
    if visits:
        latest = max(visits, key=lambda v: v.get("date", ""))
        return latest.get("date", ""), latest.get("result", "")
    return "", ""


# ── 카카오 지오코딩 함수 ──
KAKAO_API_KEY = "12a6d5580904db14be2b073e8e114a4f"

def geocode_address(address):
    """
    주소를 위도/경도로 변환 (카카오 로컬 API 사용)
    주소 검색 실패 시 키워드 검색으로 fallback
    """
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}

    # 1차: 주소 검색
    try:
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("documents"):
            doc = data["documents"][0]
            return float(doc["y"]), float(doc["x"])
    except Exception as e:
        print(f"[지오코딩 오류] {address}: {e}")

    # 2차: 키워드 검색 (건물명 등)
    try:
        url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("documents"):
            doc = data["documents"][0]
            return float(doc["y"]), float(doc["x"])
    except Exception as e:
        print(f"[키워드 검색 오류] {address}: {e}")

    return None, None


# ══════════════════════════════════════════
#  인증 라우트
# ══════════════════════════════════════════

@app.route("/login")
def login_page():
    if get_current_user():
        return redirect("/")
    return render_template("login.html", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/auth/signup", methods=["POST"])
def auth_signup():
    data = request.get_json()
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "")
    name = (data.get("name") or "").strip()

    if not username or not password or not name or not email:
        return jsonify({"error": "모든 필드를 입력하세요."}), 400
    if len(password) < 4:
        return jsonify({"error": "비밀번호는 4자 이상이어야 합니다."}), 400

    users = load_users()
    if any(u["username"] == username for u in users):
        return jsonify({"error": "이미 사용 중인 아이디입니다."}), 409

    user = {
        "id": str(uuid.uuid4()),
        "username": username,
        "email": email,
        "password": hash_pw(password),
        "name": name,
        "teamName": "",
        "isApproved": False,
        "role": "user",
        "created_at": datetime.now().isoformat(),
    }
    users.append(user)
    save_users(users)
    session["user_id"] = user["id"]
    return jsonify({"message": "회원가입 완료"})


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")

    users = load_users()
    for u in users:
        if u["username"] == username and u["password"] == hash_pw(password):
            session["user_id"] = u["id"]
            return jsonify({"message": "로그인 성공"})

    return jsonify({"error": "아이디 또는 비밀번호가 올바르지 않습니다."}), 401


@app.route("/auth/google", methods=["POST"])
def auth_google():
    data = request.get_json()
    credential = data.get("credential")
    if not credential:
        return jsonify({"error": "Google 인증 정보가 없습니다."}), 400

    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        idinfo = id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
        email = idinfo["email"].lower()
        name = idinfo.get("name", email.split("@")[0])
    except Exception as e:
        return jsonify({"error": f"Google 인증 실패: {str(e)}"}), 401

    users = load_users()
    # 기존 유저 찾기
    for u in users:
        if u.get("email") == email or u.get("username") == email:
            session["user_id"] = u["id"]
            return jsonify({"message": "Google 로그인 성공", "needTeam": not u.get("teamName")})

    # 새 유저 생성
    user = {
        "id": str(uuid.uuid4()),
        "username": email,
        "password": "",
        "name": name,
        "email": email,
        "teamName": "",
        "isApproved": False,
        "role": "user",
        "created_at": datetime.now().isoformat(),
    }
    users.append(user)
    save_users(users)
    session["user_id"] = user["id"]
    return jsonify({"message": "Google 회원가입 완료", "needTeam": True})


@app.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/login")


@app.route("/auth/me")
def auth_me():
    user = get_current_user()
    if not user:
        return jsonify({"error": "로그인 필요"}), 401
    return jsonify({
        "id": user["id"], "name": user["name"], "username": user["username"],
        "teamName": user.get("teamName", ""), "isApproved": user.get("isApproved", False),
        "role": user.get("role", "user"),
    })


@app.route("/team-setup")
def team_setup_page():
    user = get_current_user()
    if not user:
        return redirect("/login")
    if user.get("teamName"):
        return redirect("/pending" if not user.get("isApproved") else "/")
    return render_template("team-setup.html")


@app.route("/auth/set-team", methods=["POST"])
def auth_set_team():
    user = get_current_user()
    if not user:
        return jsonify({"error": "로그인 필요"}), 401
    data = request.get_json()
    team = (data.get("teamName") or "").strip()
    if not team:
        return jsonify({"error": "팀 이름을 입력하세요."}), 400

    users = load_users()
    for u in users:
        if u["id"] == user["id"]:
            u["teamName"] = team
            break
    save_users(users)
    return jsonify({"message": "팀 설정 완료"})


@app.route("/pending")
def pending_page():
    user = get_current_user()
    if not user:
        return redirect("/login")
    if user.get("isApproved"):
        return redirect("/")
    return render_template("pending.html")


@app.route("/approve")
@login_required
def approve_page():
    user = get_current_user()
    if user.get("role") != "superadmin":
        return redirect("/")
    return render_template("approve.html")


# ── 관리자 API ──

@app.route("/api/admin/pending-users")
@superadmin_required
def admin_pending_users():
    users = load_users()
    pending = [{"id": u["id"], "name": u["name"], "username": u["username"],
                "email": u.get("email", ""), "teamName": u.get("teamName", ""), "created_at": u.get("created_at", "")}
               for u in users if not u.get("isApproved") and u.get("teamName")]
    return jsonify(pending)


@app.route("/api/admin/approved-users")
@superadmin_required
def admin_approved_users():
    users = load_users()
    approved = [{"id": u["id"], "name": u["name"], "username": u["username"],
                 "email": u.get("email", ""), "teamName": u.get("teamName", ""), "role": u.get("role", "user")}
                for u in users if u.get("isApproved")]
    return jsonify(approved)


@app.route("/api/admin/approve", methods=["POST"])
@superadmin_required
def admin_approve():
    data = request.get_json()
    uid = data.get("userId")
    users = load_users()
    for u in users:
        if u["id"] == uid:
            u["isApproved"] = True
            save_users(users)
            return jsonify({"message": f"{u['name']} 승인 완료"})
    return jsonify({"error": "유저를 찾을 수 없습니다."}), 404


@app.route("/api/admin/reject", methods=["POST"])
@superadmin_required
def admin_reject():
    data = request.get_json()
    uid = data.get("userId")
    if uid and fs_delete_doc("users", uid):
        return jsonify({"message": "거절 완료"})
    return jsonify({"error": "유저를 찾을 수 없습니다."}), 404


@app.route("/api/admin/delete-user", methods=["POST"])
@superadmin_required
def admin_delete_user():
    """승인된 사용자 삭제"""
    data = request.get_json()
    uid = data.get("userId")
    if uid and fs_delete_doc("users", uid):
        return jsonify({"message": "삭제 완료"})
    return jsonify({"error": "유저를 찾을 수 없습니다."}), 404


@app.route("/api/admin/update-team", methods=["POST"])
@superadmin_required
def admin_update_team():
    """사용자 팀명 수정"""
    data = request.get_json()
    uid = data.get("userId")
    new_team = (data.get("teamName") or "").strip()
    if not uid or not new_team:
        return jsonify({"error": "userId와 teamName이 필요합니다."}), 400
    users = load_users()
    for u in users:
        if u["id"] == uid:
            u["teamName"] = new_team
            save_user(u)
            return jsonify({"message": f"팀명 '{new_team}'으로 변경 완료"})
    return jsonify({"error": "유저를 찾을 수 없습니다."}), 404


# ══════════════════════════════════════════
#  페이지 라우트 (로그인+승인 필수)
# ══════════════════════════════════════════

@app.route("/")
@login_required
def index():
    return render_template("map.html")


@app.route("/admin")
@login_required
def admin_page():
    return render_template("admin.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/calendar")
@login_required
def calendar():
    return render_template("calendar.html")


@app.route("/stores")
@login_required
def stores_page():
    return render_template("stores.html")


# ══════════════════════════════════════════
#  API 라우트 - 매장 CRUD
# ══════════════════════════════════════════

@app.route("/api/stores", methods=["GET"])
@login_required
def get_stores():
    """현재 유저의 팀 매장 목록 조회"""
    user = get_current_user()
    stores = load_stores()
    team = user.get("teamName", "")
    my_stores = [s for s in stores if s.get("teamName") == team]
    return jsonify(my_stores)


@app.route("/api/stores", methods=["POST"])
@login_required
def add_store():
    """새 매장 추가"""
    user = get_current_user()
    data = request.get_json()

    if not data or not data.get("name") or not data.get("address"):
        return jsonify({"error": "매장명과 주소는 필수입니다."}), 400

    address = data.get("address", "")
    store = {
        "id": str(uuid.uuid4()),
        "name": data.get("name", ""),
        "address": address,
        "lat": data.get("lat"),
        "lng": data.get("lng"),
        "district": extract_district(address),
        "memo": data.get("memo", ""),
        "visits": [],
        "teamName": user.get("teamName", ""),
        "created_at": datetime.now().isoformat(),
    }

    # 위도/경도가 없으면 자동 지오코딩
    if store["lat"] is None or store["lng"] is None:
        lat, lng = geocode_address(store["address"])
        store["lat"] = lat
        store["lng"] = lng

    save_store(store)
    return jsonify(store), 201


@app.route("/api/stores/<store_id>", methods=["PUT"])
@login_required
def update_store(store_id):
    """매장 정보 수정"""
    data = request.get_json()
    stores = load_stores()

    # 해당 ID의 매장 찾기
    for i, store in enumerate(stores):
        if store["id"] == store_id:
            # 전달된 필드만 업데이트
            for key in ["name", "address", "lat", "lng", "memo"]:
                if key in data:
                    stores[i][key] = data[key]
            # 주소가 변경되면 district 재추출
            if "address" in data:
                stores[i]["district"] = extract_district(data["address"])
            save_store(stores[i])
            return jsonify(stores[i])

    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


@app.route("/api/stores/<store_id>", methods=["DELETE"])
@login_required
def delete_store(store_id):
    """매장 삭제"""
    if delete_store_doc(store_id):
        return jsonify({"message": "삭제 완료"}), 200
    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


# ══════════════════════════════════════════
#  API 라우트 - 엑셀 업로드
# ══════════════════════════════════════════

@app.route("/api/upload-excel", methods=["POST"])
@login_required
def upload_excel():
    """
    엑셀(.xlsx) 파일 업로드 후 매장 일괄 등록
    엑셀 컬럼: 가맹점명, 주소, 메모
    각 주소를 카카오 API로 지오코딩
    """
    if "file" not in request.files:
        return jsonify({"error": "파일이 없습니다."}), 400

    file = request.files["file"]
    if not file.filename.endswith(".xlsx"):
        return jsonify({"error": ".xlsx 파일만 업로드 가능합니다."}), 400

    try:
        wb = openpyxl.load_workbook(file)
        ws = wb.active
    except Exception as e:
        return jsonify({"error": f"엑셀 파일 읽기 실패: {str(e)}"}), 400

    # 헤더 행 읽기 (첫 번째 행)
    headers = [cell.value for cell in ws[1]]
    required = ["가맹점명", "주소"]
    for col in required:
        if col not in headers:
            return jsonify({"error": f"필수 컬럼 '{col}'이(가) 없습니다."}), 400

    # 컬럼 인덱스 매핑
    col_map = {}
    for idx, h in enumerate(headers):
        col_map[h] = idx

    stores = load_stores()
    added = []
    errors = []

    # 데이터 행 순회 (2번째 행부터)
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        name = row[col_map["가맹점명"]] if col_map.get("가맹점명") is not None else None
        address = row[col_map["주소"]] if col_map.get("주소") is not None else None

        # 빈 행 건너뛰기
        if not name or not address:
            continue

        memo = ""
        if "메모" in col_map and col_map["메모"] < len(row):
            memo = row[col_map["메모"]] or ""

        # 카카오 지오코딩
        address_str = str(address)
        lat, lng = geocode_address(address_str)

        store = {
            "id": str(uuid.uuid4()),
            "name": str(name),
            "address": address_str,
            "lat": lat,
            "lng": lng,
            "district": extract_district(address_str),
            "memo": str(memo),
            "visits": [],
            "created_at": datetime.now().isoformat(),
        }

        if lat is None or lng is None:
            errors.append(f"행 {row_idx}: '{address}' 지오코딩 실패")

        save_store(store)
        added.append(store)

    return jsonify({
        "message": f"{len(added)}개 매장 추가 완료",
        "added": added,
        "errors": errors,
    }), 201


# ══════════════════════════════════════════
#  API 라우트 - 방문 기록 (Visit Logs)
# ══════════════════════════════════════════

@app.route("/api/stores/<store_id>/visits", methods=["GET"])
@login_required
def get_visits(store_id):
    """매장의 방문 기록 조회"""
    stores = load_stores()
    for store in stores:
        if store["id"] == store_id:
            return jsonify(store.get("visits", [])), 200
    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


@app.route("/api/stores/<store_id>/visits", methods=["POST"])
@login_required
def add_visit(store_id):
    """매장에 방문 기록 추가"""
    data = request.get_json()
    stores = load_stores()

    for i, store in enumerate(stores):
        if store["id"] == store_id:
            visit = {
                "id": str(uuid.uuid4()),
                "date": data.get("date", datetime.now().strftime("%Y-%m-%d")),
                "result": data.get("result", ""),
                "memo": data.get("memo", ""),
                "created_at": datetime.now().isoformat(),
            }
            # visits 필드가 없는 기존 데이터 호환
            if "visits" not in stores[i]:
                stores[i]["visits"] = []
            stores[i]["visits"].append(visit)
            save_store(stores[i])
            return jsonify(visit), 201

    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


@app.route("/api/stores/<store_id>/visits/<visit_id>", methods=["DELETE"])
@login_required
def delete_visit(store_id, visit_id):
    """매장의 방문 기록 삭제"""
    stores = load_stores()

    for i, store in enumerate(stores):
        if store["id"] == store_id:
            visits = store.get("visits", [])
            original_len = len(visits)
            stores[i]["visits"] = [v for v in visits if v["id"] != visit_id]

            if len(stores[i]["visits"]) == original_len:
                return jsonify({"error": "방문 기록을 찾을 수 없습니다."}), 404

            save_store(stores[i])
            return jsonify({"message": "방문 기록 삭제 완료"}), 200

    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


# ══════════════════════════════════════════
#  API 라우트 - 지역구 목록
# ══════════════════════════════════════════

@app.route("/api/districts", methods=["GET"])
@login_required
def get_districts():
    """모든 매장의 지역구 목록과 개수 조회"""
    stores = load_stores()
    district_counts = {}
    for store in stores:
        district = store.get("district", "기타")
        district_counts[district] = district_counts.get(district, 0) + 1

    result = [{"name": name, "count": count} for name, count in district_counts.items()]
    result.sort(key=lambda x: x["count"], reverse=True)
    return jsonify(result)


# ══════════════════════════════════════════
#  API 라우트 - 주소 지오코딩
# ══════════════════════════════════════════

@app.route("/api/geocode", methods=["GET"])
@login_required
def geocode():
    """주소를 위도/경도로 변환"""
    address = request.args.get("address", "")
    if not address:
        return jsonify({"error": "주소를 입력하세요."}), 400

    lat, lng = geocode_address(address)
    if lat is None:
        return jsonify({"error": "지오코딩 실패: 주소를 찾을 수 없습니다."}), 404

    return jsonify({"lat": lat, "lng": lng})


# ══════════════════════════════════════════
#  API 라우트 - 주소 자동완성 검색
# ══════════════════════════════════════════

@app.route("/api/address-search", methods=["GET"])
@login_required
def address_search():
    """주소 자동완성 (카카오 로컬 API 사용)"""
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify([])

    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}

    try:
        url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        resp = requests.get(url, headers=headers, params={"query": query, "size": 7}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("documents", []):
            results.append({
                "display_name": item.get("address_name", item.get("place_name", "")),
                "lat": float(item["y"]),
                "lng": float(item["x"]),
            })
        return jsonify(results)
    except Exception as e:
        print(f"[주소검색 오류] {query}: {e}")
        return jsonify([])


# ══════════════════════════════════════════
#  API 라우트 - 즐겨찾기 토글
# ══════════════════════════════════════════

@app.route("/api/stores/<store_id>/star", methods=["POST"])
@login_required
def toggle_star(store_id):
    """매장 즐겨찾기 토글 (starred 필드 true/false)"""
    stores = load_stores()

    for i, store in enumerate(stores):
        if store["id"] == store_id:
            current = stores[i].get("starred", False)
            stores[i]["starred"] = not current
            save_store(stores[i])
            return jsonify({
                "id": store_id,
                "starred": stores[i]["starred"],
            })

    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


# ══════════════════════════════════════════
#  API 라우트 - 일괄 삭제
# ══════════════════════════════════════════

@app.route("/api/stores/bulk-delete", methods=["POST"])
@login_required
def bulk_delete_stores():
    """매장 일괄 삭제 (body: {"ids": ["id1", "id2", ...]})"""
    data = request.get_json()
    if not data or not isinstance(data.get("ids"), list):
        return jsonify({"error": "ids 배열이 필요합니다."}), 400

    ids_to_delete = set(data["ids"])
    if not ids_to_delete:
        return jsonify({"error": "삭제할 ID가 없습니다."}), 400

    deleted_count = 0
    for sid in ids_to_delete:
        if delete_store_doc(sid):
            deleted_count += 1

    if deleted_count == 0:
        return jsonify({"error": "일치하는 매장이 없습니다."}), 404
    return jsonify({
        "message": f"{deleted_count}개 매장 삭제 완료",
        "deleted_count": deleted_count,
    }), 200


# ══════════════════════════════════════════
#  API 라우트 - CSV 내보내기
# ══════════════════════════════════════════

@app.route("/api/export/csv")
@login_required
def export_csv():
    """가맹점 목록을 BOM 포함 UTF-8 CSV로 내보내기"""
    stores = load_stores()

    output = io.StringIO()
    output.write('\ufeff')

    writer = csv.writer(output)
    writer.writerow([
        "가맹점명", "주소", "지역구", "메모",
        "최근방문일", "최근방문결과", "총방문수",
        "즐겨찾기", "등록일",
    ])

    for store in stores:
        visits = store.get("visits", [])
        last_date, last_result = get_last_visit(store)

        writer.writerow([
            store.get("name", ""),
            store.get("address", ""),
            store.get("district", ""),
            store.get("memo", ""),
            last_date,
            last_result,
            len(visits),
            "Y" if store.get("starred", False) else "N",
            store.get("created_at", ""),
        ])

    filename = f"stores_{datetime.now().strftime('%Y%m%d')}.csv"
    encoded_filename = quote(f"가맹점목록_{datetime.now().strftime('%Y%m%d')}.csv")

    response = Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"{filename}\"; "
        f"filename*=UTF-8''{encoded_filename}"
    )
    return response


# ══════════════════════════════════════════
#  API 라우트 - 엑셀 내보내기
# ══════════════════════════════════════════

@app.route("/api/export/excel")
@login_required
def export_excel():
    """가맹점 목록을 .xlsx로 내보내기 (시트1: 목록, 시트2: 방문기록)"""
    stores = load_stores()
    wb = openpyxl.Workbook()

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")

    def style_header_row(ws, col_count):
        for col in range(1, col_count + 1):
            cell = ws.cell(row=1, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment

    # 시트1: 가맹점 목록
    ws1 = wb.active
    ws1.title = "가맹점 목록"
    headers1 = ["가맹점명", "주소", "지역구", "메모", "최근방문일", "최근방문결과", "총방문수", "즐겨찾기", "등록일"]
    ws1.append(headers1)
    style_header_row(ws1, len(headers1))

    for store in stores:
        visits = store.get("visits", [])
        last_date, last_result = get_last_visit(store)

        ws1.append([
            store.get("name", ""),
            store.get("address", ""),
            store.get("district", ""),
            store.get("memo", ""),
            last_date,
            last_result,
            len(visits),
            "Y" if store.get("starred", False) else "N",
            store.get("created_at", ""),
        ])

    for col_idx, header in enumerate(headers1, 1):
        ws1.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(len(header) * 2.5, 12)

    # 시트2: 전체 방문기록
    ws2 = wb.create_sheet("전체 방문기록")
    headers2 = ["가맹점명", "주소", "방문일", "방문결과", "방문메모"]
    ws2.append(headers2)
    style_header_row(ws2, len(headers2))

    for store in stores:
        for visit in store.get("visits", []):
            ws2.append([
                store.get("name", ""),
                store.get("address", ""),
                visit.get("date", ""),
                visit.get("result", ""),
                visit.get("memo", ""),
            ])

    for col_idx, header in enumerate(headers2, 1):
        ws2.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(len(header) * 2.5, 12)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"stores_{datetime.now().strftime('%Y%m%d')}.xlsx"

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


# ══════════════════════════════════════════
#  API 라우트 - JSON 백업 다운로드
# ══════════════════════════════════════════

@app.route("/api/backup")
@login_required
def backup_json():
    """stores.json 파일 그대로 다운로드"""
    if not os.path.exists(STORES_FILE):
        return jsonify({"error": "백업 파일이 존재하지 않습니다."}), 404

    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    return send_file(
        STORES_FILE,
        mimetype="application/json; charset=utf-8",
        as_attachment=True,
        download_name=filename,
    )


# ── 초기화 + 서버 실행 ──
ensure_superadmin()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG", "true").lower() == "true")

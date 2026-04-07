"""
Point3 CRM - Flask 백엔드 서버
"""

import os
import json
import re
import uuid
import csv
import io
from datetime import datetime
from urllib.parse import quote

from flask import Flask, request, jsonify, render_template, Response, send_file
from flask_cors import CORS
import requests
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# ── Flask 앱 초기화 ──
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
CORS(app)

# ── 데이터 파일 경로 설정 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STORES_FILE = os.path.join(DATA_DIR, "stores.json")

# ── 데이터 디렉토리 및 파일 자동 생성 ──
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
if not os.path.exists(STORES_FILE):
    with open(STORES_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False)


def load_stores():
    """stores.json에서 매장 목록 로드 (항상 파일에서 읽기)"""
    with open(STORES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_stores(stores):
    """매장 목록을 stores.json에 저장"""
    with open(STORES_FILE, "w", encoding="utf-8") as f:
        json.dump(stores, f, ensure_ascii=False, indent=2)


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
#  페이지 라우트
# ══════════════════════════════════════════

@app.route("/")
def index():
    """메인 지도 페이지"""
    return render_template("map.html")


@app.route("/admin")
def admin():
    """가맹점 등록 페이지"""
    return render_template("admin.html")


@app.route("/dashboard")
def dashboard():
    """영업 통계 대시보드"""
    return render_template("dashboard.html")


@app.route("/calendar")
def calendar():
    """방문 캘린더 페이지"""
    return render_template("calendar.html")


@app.route("/stores")
def stores_page():
    """가맹점 목록 페이지"""
    return render_template("stores.html")


# ══════════════════════════════════════════
#  API 라우트 - 매장 CRUD
# ══════════════════════════════════════════

@app.route("/api/stores", methods=["GET"])
def get_stores():
    """모든 매장 목록 조회"""
    stores = load_stores()
    return jsonify(stores)


@app.route("/api/stores", methods=["POST"])
def add_store():
    """새 매장 추가"""
    data = request.get_json()

    # 필수 필드 검증
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
        "created_at": datetime.now().isoformat(),
    }

    # 위도/경도가 없으면 자동 지오코딩
    if store["lat"] is None or store["lng"] is None:
        lat, lng = geocode_address(store["address"])
        store["lat"] = lat
        store["lng"] = lng

    stores = load_stores()
    stores.append(store)
    save_stores(stores)

    return jsonify(store), 201


@app.route("/api/stores/<store_id>", methods=["PUT"])
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
            save_stores(stores)
            return jsonify(stores[i])

    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


@app.route("/api/stores/<store_id>", methods=["DELETE"])
def delete_store(store_id):
    """매장 삭제"""
    stores = load_stores()
    original_len = len(stores)
    stores = [s for s in stores if s["id"] != store_id]

    if len(stores) == original_len:
        return jsonify({"error": "매장을 찾을 수 없습니다."}), 404

    save_stores(stores)
    return jsonify({"message": "삭제 완료"}), 200


# ══════════════════════════════════════════
#  API 라우트 - 엑셀 업로드
# ══════════════════════════════════════════

@app.route("/api/upload-excel", methods=["POST"])
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

        stores.append(store)
        added.append(store)

    save_stores(stores)

    return jsonify({
        "message": f"{len(added)}개 매장 추가 완료",
        "added": added,
        "errors": errors,
    }), 201


# ══════════════════════════════════════════
#  API 라우트 - 방문 기록 (Visit Logs)
# ══════════════════════════════════════════

@app.route("/api/stores/<store_id>/visits", methods=["GET"])
def get_visits(store_id):
    """매장의 방문 기록 조회"""
    stores = load_stores()
    for store in stores:
        if store["id"] == store_id:
            return jsonify(store.get("visits", [])), 200
    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


@app.route("/api/stores/<store_id>/visits", methods=["POST"])
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
            save_stores(stores)
            return jsonify(visit), 201

    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


@app.route("/api/stores/<store_id>/visits/<visit_id>", methods=["DELETE"])
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

            save_stores(stores)
            return jsonify({"message": "방문 기록 삭제 완료"}), 200

    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


# ══════════════════════════════════════════
#  API 라우트 - 지역구 목록
# ══════════════════════════════════════════

@app.route("/api/districts", methods=["GET"])
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
def toggle_star(store_id):
    """매장 즐겨찾기 토글 (starred 필드 true/false)"""
    stores = load_stores()

    for i, store in enumerate(stores):
        if store["id"] == store_id:
            current = stores[i].get("starred", False)
            stores[i]["starred"] = not current
            save_stores(stores)
            return jsonify({
                "id": store_id,
                "starred": stores[i]["starred"],
            })

    return jsonify({"error": "매장을 찾을 수 없습니다."}), 404


# ══════════════════════════════════════════
#  API 라우트 - 일괄 삭제
# ══════════════════════════════════════════

@app.route("/api/stores/bulk-delete", methods=["POST"])
def bulk_delete_stores():
    """매장 일괄 삭제 (body: {"ids": ["id1", "id2", ...]})"""
    data = request.get_json()
    if not data or not isinstance(data.get("ids"), list):
        return jsonify({"error": "ids 배열이 필요합니다."}), 400

    ids_to_delete = set(data["ids"])
    if not ids_to_delete:
        return jsonify({"error": "삭제할 ID가 없습니다."}), 400

    stores = load_stores()
    original_len = len(stores)
    stores = [s for s in stores if s["id"] not in ids_to_delete]
    deleted_count = original_len - len(stores)

    if deleted_count == 0:
        return jsonify({"error": "일치하는 매장이 없습니다."}), 404

    save_stores(stores)
    return jsonify({
        "message": f"{deleted_count}개 매장 삭제 완료",
        "deleted_count": deleted_count,
    }), 200


# ══════════════════════════════════════════
#  API 라우트 - CSV 내보내기
# ══════════════════════════════════════════

@app.route("/api/export/csv")
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


# ── 서버 실행 ──
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG", "true").lower() == "true")

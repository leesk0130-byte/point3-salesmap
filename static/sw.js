const CACHE_NAME = 'point3-v2';
const APP_SHELL = [
  '/',
  '/static/manifest.json',
  '/static/icon.svg'
];

// 설치: 앱 셸 캐시
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(APP_SHELL);
    })
  );
  self.skipWaiting();
});

// 활성화: 이전 캐시 정리
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// 요청 가로채기
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API 호출 → 캐싱 없이 네트워크 직접 요청
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/search')) {
    return;  // 서비스 워커가 개입하지 않음 → 브라우저 기본 네트워크 요청
  }

  // 정적 자원 → 네트워크 우선, 실패 시 캐시 폴백
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response.ok) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
      }
      return response;
    }).catch(() => {
      return caches.match(event.request).then((cached) => {
        if (cached) return cached;
        // 오프라인 폴백: HTML 요청이면 메인 페이지 반환
        if (event.request.headers.get('accept')?.includes('text/html')) {
          return caches.match('/');
        }
      });
    })
  );
});

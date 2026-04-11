const CACHE_NAME = 'point3-v3';
const APP_SHELL = [
  '/',
  '/static/manifest.json',
  '/static/icon.svg',
  '/static/offline.html'
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

  // API 호출: Network-only, 실패 시 캐시된 응답 반환 (stale-while-revalidate 패턴)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).then((response) => {
        // /api/stores, /api/stats 등은 캐시에 저장
        if (response.ok && (url.pathname.includes('/stores') || url.pathname.includes('/stats') || url.pathname.includes('/calendar'))) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => {
        // 오프라인 시 캐시된 API 응답 반환
        return caches.match(event.request).then((cached) => {
          if (cached) return cached;
          return new Response(JSON.stringify({ error: 'offline' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
          });
        });
      })
    );
    return;
  }

  // /search 는 서비스 워커 개입 없음
  if (url.pathname.startsWith('/search')) {
    return;
  }

  // 정적 자원 및 페이지 → 네트워크 우선, 실패 시 캐시 폴백
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
        // 오프라인 폴백: HTML 요청이면 오프라인 페이지 반환
        if (event.request.headers.get('accept')?.includes('text/html')) {
          return caches.match('/static/offline.html');
        }
      });
    })
  );
});

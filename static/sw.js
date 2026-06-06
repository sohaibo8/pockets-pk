const CACHE = 'pockets-pk-v1';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/'])));
});
self.addEventListener('fetch', e => {
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
self.addEventListener('push', e => {
  e.waitUntil(self.registration.showNotification('Pockets PK', {
    body: e.data ? e.data.text() : 'New transaction pending',
    icon: '/icon.png',
    badge: '/icon.png'
  }));
});

const CACHE = "orion-shell-v2-m2";
const SHELL = ["/", "/manifest.webmanifest", "/orion-icon.svg"];
self.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL))));
self.addEventListener("activate", (event) => event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))));
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Never retain authenticated API responses or cross-origin development data.
  if (event.request.method !== "GET" || url.origin !== self.location.origin || !(SHELL.includes(url.pathname) || url.pathname.startsWith("/assets/"))) return;
  event.respondWith(fetch(event.request).then((response) => { const copy = response.clone(); caches.open(CACHE).then((cache) => cache.put(event.request, copy)); return response; }).catch(() => caches.match(event.request).then((cached) => cached || caches.match("/"))));
});

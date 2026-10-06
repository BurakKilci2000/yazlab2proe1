/* Kocaeli Haber Haritası - arayüz mantığı
 *
 * - Filtreler değiştiğinde /api/news çağrılır, işaretler yenilenir. Sayfa yeniden yüklenmez.
 * - Her haber türünün kendi rengi ve sembolü vardır (işaret ve listede aynı).
 * - İşarete tıklanınca bilgi penceresi açılır: başlık, tarih, kaynaklar, "Habere git".
 * - Haber metinleri dış sitelerden geldiği için DOM'a her zaman textContent ile
 *   yazılır (innerHTML ile yazılmaz) -> zararlı HTML/JS çalıştırılamaz.
 * - Harita iki sağlayıcıyla çalışabilir (.env -> MAP_PROVIDER):
 *     google : Google Maps JavaScript API (proje dokümanının istediği)
 *     osm    : Leaflet + OpenStreetMap (kart/anahtar gerektirmeyen geçici seçenek)
 *   İkisi de aynı küçük arayüzü (adaptör) uygular; kodun geri kalanı hangisinin
 *   kullanıldığını bilmez.
 */
(function () {
  "use strict";

  const CFG = window.APP_CONFIG;
  const TYPES = CFG.types;
  const TYPE_BY_NAME = Object.fromEntries(TYPES.map((t) => [t.name, t]));

  // 24x24 çizgi ikonları (sabit, güvenilir içerik)
  const ICONS = {
    trafik:
      '<path d="M4 15.5V12l2.2-5h11.6L20 12v3.5z"/><path d="M4 12h16"/>' +
      '<circle cx="7.5" cy="16.5" r="1.8"/><circle cx="16.5" cy="16.5" r="1.8"/>',
    yangin:
      '<path d="M12 3c.5 3-2 4.5-3.5 6.8A6 6 0 1 0 18 14c0-2.6-1.4-4.3-2.6-5.6-.3 1.6-1.1 2.6-2.2 3 .9-2.8.2-5.9-1.2-8.4z"/>',
    elektrik: '<path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2z"/>',
    hirsizlik:
      '<path d="M3 10c0-1.5 1.5-2.5 3-2.5 2 0 3.5 1.5 6 1.5s4-1.5 6-1.5c1.5 0 3 1 3 2.5 0 3-2 5.5-4.5 5.5-2 0-3-1.5-4.5-1.5s-2.5 1.5-4.5 1.5C5 15.5 3 13 3 10z"/>' +
      '<path d="M6.8 11h2.6M14.6 11h2.6"/>',
    kultur:
      '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  };

  const state = {
    adapter: null,               // GoogleAdapter veya LeafletAdapter
    markers: new Map(),          // haber id -> { marker, el, news }
    selectedTypes: new Set(TYPES.map((t) => t.name)),
    activeId: null,
    requestSeq: 0,
    wasRunning: false,
  };

  const $ = (id) => document.getElementById(id);
  const dateFmt = new Intl.DateTimeFormat("tr-TR", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: "Europe/Istanbul",
  });
  const shortDateFmt = new Intl.DateTimeFormat("tr-TR", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Istanbul",
  });

  function iconSvg(slug, size) {
    return (
      `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" ` +
      `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[slug]}</svg>`
    );
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function paint(node, type) {
    node.style.setProperty("--pin", type.color);
    node.style.setProperty("--glyph", type.glyph);
  }

  function badge(type, size) {
    const b = el("span", "badge");
    paint(b, type);
    b.innerHTML = iconSvg(type.slug, size);
    return b;
  }

  // ------------------------------------------------------------- tarih yardımcıları
  function isoLocalDate(d) {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit", day: "2-digit",
    }).format(d);
    return parts; // YYYY-MM-DD
  }

  function setRange(days) {
    const end = new Date();
    const start = new Date(end.getTime() - (days - 1) * 86400000);
    $("startDate").value = isoLocalDate(start);
    $("endDate").value = isoLocalDate(end);
    document.querySelectorAll(".quick button").forEach((b) => {
      b.setAttribute("aria-pressed", String(Number(b.dataset.days) === days));
    });
  }

  // ------------------------------------------------------------- filtre paneli
  function buildTypeList() {
    const list = $("typeList");
    TYPES.forEach((type) => {
      const li = el("li");
      const btn = el("button", "type-toggle");
      btn.type = "button";
      btn.dataset.type = type.name;
      btn.setAttribute("aria-pressed", "true");
      btn.append(badge(type, 15), el("span", "name", type.name), el("span", "num", "0"));
      btn.addEventListener("click", () => {
        if (state.selectedTypes.has(type.name)) state.selectedTypes.delete(type.name);
        else state.selectedTypes.add(type.name);
        btn.setAttribute("aria-pressed", String(state.selectedTypes.has(type.name)));
        loadNews();
      });
      li.append(btn);
      list.append(li);
    });
  }

  function filterParams(includeTypes) {
    const p = new URLSearchParams();
    if (includeTypes) p.set("types", [...state.selectedTypes].join(","));
    const district = $("district").value;
    if (district) p.set("district", district);
    if ($("startDate").value) p.set("start", $("startDate").value);
    if ($("endDate").value) p.set("end", $("endDate").value);
    return p;
  }

  async function loadNews() {
    const seq = ++state.requestSeq;   // eski isteğin geç gelen cevabını yok saymak için
    try {
      const [newsRes, statsRes] = await Promise.all([
        fetch(`/api/news?${filterParams(true)}`),
        fetch(`/api/stats?${filterParams(false)}`),
      ]);
      if (!newsRes.ok || !statsRes.ok) throw new Error("Sunucu hatası");
      const news = await newsRes.json();
      const stats = await statsRes.json();
      if (seq !== state.requestSeq) return;
      renderCounts(stats.counts);
      renderList(news.items);
      renderMarkers(news.items);
    } catch (err) {
      if (seq !== state.requestSeq) return;
      showStatus("Haberler alınamadı. Sunucunun çalıştığını kontrol edin.", "error");
    }
  }

  function renderCounts(counts) {
    document.querySelectorAll(".type-toggle").forEach((btn) => {
      btn.querySelector(".num").textContent = counts[btn.dataset.type] ?? 0;
    });
  }

  function renderList(items) {
    const list = $("newsList");
    list.replaceChildren();
    $("newsCount").textContent = items.length ? `(${items.length})` : "";
    if (!items.length) {
      list.append(el("li", "empty", "Bu filtrelere uyan haber yok. Tarih aralığını genişletin veya haberleri tarayın."));
      return;
    }
    items.slice(0, 60).forEach((n) => {
      const type = TYPE_BY_NAME[n.type];
      const li = el("li", "news-item");
      const btn = el("button");
      btn.type = "button";
      const text = el("span");
      const where = n.location?.label || n.district || "";
      text.append(
        el("span", "t", n.title),
        el("span", "m", `${where}${where ? " · " : ""}${shortDateFmt.format(new Date(n.published_at))}`),
      );
      btn.append(badge(type, 15), text);
      btn.addEventListener("click", () => focusNews(n.id));
      li.append(btn);
      list.append(li);
    });
  }

  // ------------------------------------------------------------- harita
  function spreadPosition(lat, lng, index) {
    // Aynı koordinattaki işaretler üst üste binmesin diye küçük bir sarmal üzerinde dağıtılır.
    if (index === 0) return { lat, lng };
    const angle = index * 2.399963;              // altın açı
    const r = 0.0011 * Math.sqrt(index);
    return { lat: lat + r * Math.sin(angle), lng: lng + (r * Math.cos(angle)) / Math.cos((lat * Math.PI) / 180) };
  }

  function createPin(type) {
    const pin = el("div", "pin");
    const body = el("span", "pin-body");
    paint(pin, type);
    body.innerHTML = iconSvg(type.slug, 17);
    pin.append(body);
    return pin;
  }

  function renderMarkers(items) {
    const map = state.adapter;
    if (!map) return;
    state.markers.forEach(({ marker }) => map.removeMarker(marker));
    state.markers.clear();
    map.closeInfo();

    const seen = new Map();
    items.forEach((n) => {
      if (typeof n.lat !== "number" || typeof n.lng !== "number") return;
      const type = TYPE_BY_NAME[n.type];
      const key = `${n.lat.toFixed(5)},${n.lng.toFixed(5)}`;
      const idx = seen.get(key) || 0;
      seen.set(key, idx + 1);

      const pin = createPin(type);
      const marker = map.addMarker(spreadPosition(n.lat, n.lng, idx), pin,
        `${n.type}: ${n.title}`, () => openInfo(n.id));
      state.markers.set(n.id, { marker, el: pin, news: n });
    });
  }

  function buildInfo(n) {
    const type = TYPE_BY_NAME[n.type];
    const root = el("div", "info");
    paint(root, type);

    const head = el("div", "type");
    head.innerHTML = iconSvg(type.slug, 14);
    head.append(document.createTextNode(n.type));

    const meta = el("p", "meta", `${dateFmt.format(new Date(n.published_at))} · ${n.location_text || ""}`);

    const sourcesTitle = el("div", "meta", n.sources.length > 1
      ? `Bu haber ${n.sources.length} kaynakta yer aldı:` : "Kaynak:");
    const sources = el("ul", "sources");
    n.sources.forEach((s) => {
      const li = el("li");
      const a = el("a", null, s.site_name);
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      li.append(a);
      sources.append(li);
    });

    const go = el("a", "go", "Habere git");
    go.href = n.url;
    go.target = "_blank";
    go.rel = "noopener noreferrer";

    const details = el("details");
    details.append(el("summary", null, "Tespit edilen konumlar"));
    const ul = el("ul");
    (n.location.candidates || []).forEach((c) => ul.append(el("li", null, `${c.text} (${c.kind})`)));
    if (n.location.formatted_address) {
      ul.append(el("li", null, `Google: ${n.location.formatted_address}`));
    }
    details.append(ul);

    root.append(head, el("h3", null, n.title), meta, sourcesTitle, sources, go, details);
    return root;
  }

  function openInfo(id) {
    const entry = state.markers.get(id);
    if (!entry) return;
    if (state.activeId && state.markers.has(state.activeId)) {
      state.markers.get(state.activeId).el.classList.remove("is-active");
    }
    state.activeId = id;
    entry.el.classList.add("is-active");
    state.adapter.openInfo(entry.marker, buildInfo(entry.news));
  }

  function focusNews(id) {
    const entry = state.markers.get(id);
    if (!entry) return;
    state.adapter.focus(entry.marker, 13);
    openInfo(id);
    if (window.matchMedia("(max-width: 760px)").matches) {
      $("map").scrollIntoView({ behavior: "smooth" });
    }
  }

  // ------------------------------------------------------------- tarama
  function showStatus(text, kind) {
    const s = $("scrapeStatus");
    s.textContent = text;
    s.className = "status" + (kind ? ` is-${kind}` : "");
  }

  function describeRun(run) {
    if (!run || !run.finished_at) return "Henüz tarama yapılmadı";
    return `Son tarama ${dateFmt.format(new Date(run.finished_at))}: ` +
      `${run.saved} yeni haber, ${run.merged} birleştirildi`;
  }

  async function pollStatus() {
    try {
      const res = await fetch("/api/scrape/status");
      const s = await res.json();
      $("lastRun").textContent = describeRun(s.last_run);
      $("scrapeBtn").disabled = s.running;
      if (s.running) {
        showStatus(s.message || "Tarama sürüyor", "running");
        state.wasRunning = true;
        setTimeout(pollStatus, 2000);
      } else {
        if (s.error) showStatus(s.message, "error");
        else if (state.wasRunning && s.summary) {
          showStatus(`Tamamlandı: ${s.summary.saved} yeni, ${s.summary.merged} birleştirildi, ` +
            `${s.summary.skipped} haber kapsam dışı ya da atlandı.`);
        }
        if (state.wasRunning) loadNews();
        state.wasRunning = false;
      }
    } catch (err) {
      showStatus("Tarama durumu alınamadı.", "error");
    }
  }

  async function startScrape() {
    const days = Math.min(Math.max(parseInt($("scrapeDays").value, 10) || CFG.defaultDays, 1), 30);
    $("scrapeBtn").disabled = true;
    try {
      const res = await fetch("/api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days }),
      });
      const data = await res.json();
      if (!data.started) showStatus(data.message || "Bir tarama zaten sürüyor", "running");
      state.wasRunning = true;
      pollStatus();
    } catch (err) {
      $("scrapeBtn").disabled = false;
      showStatus("Tarama başlatılamadı.", "error");
    }
  }

  // ------------------------------------------------------------- başlangıç
  function bindControls() {
    document.querySelectorAll(".quick button").forEach((b) => {
      b.addEventListener("click", () => { setRange(Number(b.dataset.days)); loadNews(); });
    });
    ["startDate", "endDate"].forEach((id) => $(id).addEventListener("change", () => {
      document.querySelectorAll(".quick button").forEach((b) => b.setAttribute("aria-pressed", "false"));
      loadNews();
    }));
    $("district").addEventListener("change", loadNews);
    $("applyBtn").addEventListener("click", loadNews);
    $("resetBtn").addEventListener("click", () => {
      state.selectedTypes = new Set(TYPES.map((t) => t.name));
      document.querySelectorAll(".type-toggle").forEach((b) => b.setAttribute("aria-pressed", "true"));
      $("district").value = "";
      setRange(CFG.defaultDays);
      if (state.adapter) state.adapter.reset();
      loadNews();
    });
    $("scrapeBtn").addEventListener("click", startScrape);
  }

  function showMapNotice(text) {
    const n = $("mapNotice");
    n.textContent = text;
    n.hidden = false;
  }

  function onInfoClosed() {
    if (state.activeId && state.markers.has(state.activeId)) {
      state.markers.get(state.activeId).el.classList.remove("is-active");
    }
    state.activeId = null;
  }

  // ------------------------------------------------------------- harita adaptörleri
  // Her adaptör aynı metotları sağlar:
  //   addMarker(pos, el, title, onClick) -> işaret     removeMarker(işaret)
  //   openInfo(işaret, içerikEl)   closeInfo()   focus(işaret, zoom)   reset()

  async function createGoogleAdapter() {
    const { Map, InfoWindow } = await google.maps.importLibrary("maps");
    const { AdvancedMarkerElement } = await google.maps.importLibrary("marker");
    const map = new Map($("map"), {
      center: CFG.center, zoom: CFG.zoom, mapId: CFG.mapId,
      mapTypeControl: false, streetViewControl: false, fullscreenControl: true,
      gestureHandling: "greedy",
    });
    const info = new InfoWindow({ maxWidth: 320 });
    let lastActive = null;
    info.addListener("closeclick", onInfoClosed);
    return {
      addMarker(position, el, title, onClick) {
        const marker = new AdvancedMarkerElement({ map, position, content: el, title });
        marker.addListener("click", onClick);
        return marker;
      },
      removeMarker(marker) { marker.map = null; },
      openInfo(marker, content) {
        if (lastActive) lastActive.zIndex = null;
        marker.zIndex = 1000;                  // seçili işaret en üstte
        lastActive = marker;
        info.setContent(content);
        info.open({ map, anchor: marker });
      },
      closeInfo() { info.close(); },
      focus(marker, zoom) {
        map.panTo(marker.position);
        if (map.getZoom() < zoom) map.setZoom(zoom);
      },
      reset() { map.setCenter(CFG.center); map.setZoom(CFG.zoom); },
    };
  }

  function createLeafletAdapter() {
    const map = L.map("map", { zoomControl: true }).setView([CFG.center.lat, CFG.center.lng], CFG.zoom);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> katkıda bulunanlar',
    }).addTo(map);
    const popup = L.popup({ maxWidth: 320, offset: [0, -34], autoPanPadding: [24, 24] });
    let lastActive = null;
    map.on("popupclose", onInfoClosed);
    return {
      addMarker(position, el, title, onClick) {
        // İşaretin alt-orta noktası (iğne ucu) koordinata denk gelir; Google ile aynı.
        const icon = L.divIcon({ html: el, className: "pin-icon", iconSize: [34, 34], iconAnchor: [17, 34] });
        // riseOnHover: üst üste binen işaretlerde fareyle gelinen öne çıkar.
        const marker = L.marker([position.lat, position.lng], { icon, title, keyboard: true, riseOnHover: true })
          .addTo(map);
        marker.on("click", onClick);
        return marker;
      },
      removeMarker(marker) { marker.remove(); },
      openInfo(marker, content) {
        if (lastActive) lastActive.setZIndexOffset(0);
        marker.setZIndexOffset(1000);          // seçili işaret en üstte
        lastActive = marker;
        popup.setLatLng(marker.getLatLng()).setContent(content).openOn(map);
      },
      closeInfo() { map.closePopup(); },
      focus(marker, zoom) { map.setView(marker.getLatLng(), Math.max(map.getZoom(), zoom)); },
      reset() { map.setView([CFG.center.lat, CFG.center.lng], CFG.zoom); },
    };
  }

  // Google Maps betiği yüklenince bu fonksiyonu çağırır (callback=initMap).
  // OpenStreetMap seçiliyse aşağıda doğrudan çağrılır.
  window.initMap = async function () {
    try {
      state.adapter = CFG.mapProvider === "google" ? await createGoogleAdapter() : createLeafletAdapter();
      loadNews();
    } catch (err) {
      showMapNotice(CFG.mapProvider === "google"
        ? "Harita yüklenemedi. Maps JavaScript API anahtarını ve yetkilerini kontrol edin."
        : "Harita yüklenemedi. İnternet bağlantınızı kontrol edin.");
      loadNews();
    }
  };

  // Google anahtarı geçersizse Google bu fonksiyonu çağırır.
  window.gm_authFailure = function () {
    showMapNotice("Google Maps anahtarı reddedildi. Anahtarın Maps JavaScript API için yetkili olduğunu ve " +
      "HTTP referrer kısıtlamasının bu adresi kapsadığını kontrol edin.");
  };

  // Betik sayfanın sonunda yüklendiği için DOM hazırdır. Panel, Google Maps betiğinden
  // önce kurulur; böylece initMap çağrıldığında filtre değerleri zaten doludur.
  buildTypeList();
  bindControls();
  setRange(CFG.defaultDays);
  pollStatus();
  if (CFG.mapProvider === "osm") {
    window.initMap();
  } else if (!CFG.hasMapsKey) {
    showMapNotice("Harita için .env dosyasına GOOGLE_MAPS_JS_API_KEY ekleyin. Filtreler ve haber listesi yine de çalışır.");
    loadNews();
  }
})();

(function () {
  "use strict";
  var app = document.getElementById("app"), api = "/api";
  var state = {articles: [], query: "", theme: localStorage.getItem("wiki-theme") || "dark"};
  var categories = [
    ["01", "Начало работы", "Основные правила работы с помощником и базой знаний"],
    ["02", "Подготовка документов", "Реквизиты, бланки и требования к проектам"],
    ["03", "Согласование и визирование", "Маршрут проекта, визы и сроки"],
    ["04", "Регистрация и хранение", "Регистрация, исполнение и хранение документов"],
    ["05", "Матрица визирования", "Правила выбора обязательных согласующих"],
    ["06", "Информационная безопасность", "Работа со служебной информацией и доступами"],
    ["07", "Проверка черновика", "Проверка готового документа по инструкции"],
    ["08", "Шаблоны документов", "Подготовка документов по модульным бланкам"]
  ];

  function esc(value) {
    return String(value || "").replace(/[&<>"']/g, function (c) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];
    });
  }
  function icon() { return '<span class="search-icon" aria-hidden="true"></span>'; }
  function header() {
    return '<header class="topbar">' +
      '<button class="theme mobile-menu" data-action="menu" type="button">Menu</button>' +
      '<a class="brand" href="#/"><strong>Wiki</strong></a>' +
      '<nav class="nav"><a href="#/">Обзор</a><a href="#/wiki">База знаний</a><a href="#/templates">Шаблоны</a><a href="#/review">Проверить</a><a href="#/versions">Версии</a></nav>' +
      '<label class="top-search">' + icon() + '<input data-search placeholder="Поиск по базе знаний..." value="' + esc(state.query) + '"><div class="results" data-results></div></label>' +
      '<button class="theme" data-action="theme" type="button">Тема</button></header>';
  }
  function footer() { return '<footer class="footer"><div class="container">BankAssistant Wiki</div></footer>'; }
  function searchBox() {
    return '<label class="hero-search">' + icon() + '<input data-search placeholder="Поиск по базе знаний..." value="' + esc(state.query) + '"><div class="results" data-results></div></label>';
  }
  function categoryCard(c) {
    return '<a class="card category-card" href="#/wiki?cat=' + encodeURIComponent(c[1]) + '">' +
      '<span class="category-number">' + c[0] + '</span><h3>' + esc(c[1]) + '</h3><p>' + esc(c[2]) + '</p></a>';
  }
  function articleCard(a) {
    var title = Array.isArray(a) ? a[1] : a.title;
    var desc = Array.isArray(a) ? a[3] : (a.plain || a.text || "");
    var label = Array.isArray(a) ? a[2] : ("п. " + (a.point || "—"));
    return '<a class="card article-card" href="#/article/' + encodeURIComponent(a.id || a[0]) + '">' +
      '<span class="eyebrow">' + esc(label) + '</span><h3>' + esc(title) + '</h3><p>' + esc(desc) + '</p></a>';
  }
  function home() {
    return header() + '<main><section class="hero container"><span class="eyebrow">BankAssistant Wiki</span>' +
      '<h1>База знаний</h1><p>Находите нужный пункт инструкции и открывайте его источник.</p>' + searchBox() +
      '</section><section class="section container"><div class="section-head"><h2>Разделы</h2></div><div class="grid">' +
      categories.map(categoryCard).join("") + '</div></section><section class="section container"><div class="section-head"><h2>Последние материалы</h2>' +
      '<a class="btn secondary" href="#/wiki">Все материалы</a></div><div class="articles">' +
      state.articles.slice(0, 6).map(articleCard).join("") +
      (state.articles.length ? "" : '<div class="empty">Материалы загружаются…</div>') + '</div></section></main>' + footer();
  }
  function wiki() {
    return header() + '<main class="container wiki-page"><div class="page-head"><span class="eyebrow">BankAssistant Wiki</span>' +
      '<h1>Все материалы</h1><p>Активные пункты документов, доступные в базе знаний.</p></div><div class="articles">' +
      state.articles.map(articleCard).join("") + (state.articles.length ? "" : '<div class="empty">Материалы загружаются…</div>') +
      '</div></main>' + footer();
  }
  function article(id) {
    var item = state.articles.find(function (a) { return a.id === id; });
    if (!item) return header() + '<main class="container article-page"><div class="empty">Материал не найден.</div></main>' + footer();
    var source = (item.doc || "") + (item.version ? " · версия " + item.version : "") + (item.point ? " · п. " + item.point : "");
    return header() + '<main class="container article-page"><div class="crumbs"><a href="#/">Обзор</a> / <a href="#/wiki">База знаний</a></div>' +
      '<span class="eyebrow">Пункт инструкции · ' + esc(item.point || "—") + '</span><h1>' + esc(item.title) + '</h1>' +
      '<p class="article-lead">' + esc(item.plain || "") + '</p><div class="article-meta">Источник: ' + esc(source) + '</div>' +
      '<div class="article-body"><p>' + esc(item.text || item.plain || "") + '</p></div>' +
      '<div class="article-actions"><a class="btn secondary" href="#/review">Проверить документ</a></div></main>' + footer();
  }
  function upload() {
    return header() + '<main class="container narrow-page"><div class="crumbs"><a href="#/">Обзор</a> / Обновить базу</div>' +
      '<h1>Загрузить новую версию</h1><form class="upload" data-upload><label>Название документа<input name="doc" required value="Инструкция по документообороту"></label>' +
      '<label>Новая версия<input name="version" required value="2.0"></label><label>Файл инструкции<input name="file" type="file" accept=".pdf,.docx,.txt,.md" required></label>' +
      '<button class="btn">Активировать версию</button><div class="notice" data-upload-result></div></form></main>' + footer();
  }
  function review() {
    return header() + '<main class="container narrow-page"><div class="crumbs"><a href="#/">Обзор</a> / Проверка</div>' +
      '<h1>Проверить документ</h1><p class="article-lead">Сопоставьте проект с активной инструкцией.</p><form class="upload" data-review>' +
      '<label>Файл проекта<input name="file" type="file" accept=".pdf,.docx,.txt,.md" required></label><button class="btn">Проверить</button>' +
      '<div class="notice" data-review-result></div></form></main>' + footer();
  }
  function templates() {
    return header() + '<main class="container narrow-page"><div class="crumbs"><a href="#/">Обзор</a> / Шаблоны</div><h1>Шаблоны документов</h1>' +
      '<div class="articles" data-templates><div class="empty">Загрузка…</div></div></main>' + footer();
  }
  function versions() {
    return header() + '<main class="container narrow-page"><div class="crumbs"><a href="#/">Обзор</a> / Версии</div><h1>Версии документов</h1>' +
      '<div class="articles" data-versions><div class="empty">Загрузка…</div></div></main>' + footer();
  }
  function render() {
    var hash = location.hash || "#/", match = hash.match(/^#\/article\/(.+)/);
    app.innerHTML = match ? article(decodeURIComponent(match[1])) :
      hash.indexOf("#/upload") === 0 ? upload() : hash.indexOf("#/review") === 0 ? review() :
      hash.indexOf("#/templates") === 0 ? templates() : hash.indexOf("#/versions") === 0 ? versions() :
      hash.indexOf("#/wiki") === 0 ? wiki() : home();
    bind();
  }
  function showResults(input) {
    var box = input.parentNode.querySelector("[data-results]");
    if (!box || !state.query) { if (box) box.innerHTML = ""; return; }
    fetch(api + "/kb/search?q=" + encodeURIComponent(state.query)).then(function (r) { return r.json(); }).then(function (found) {
      box.innerHTML = found.length ? found.slice(0, 8).map(function (a) {
        return '<a class="result" href="#/article/' + encodeURIComponent(a.id) + '">' + esc("п. " + a.point + " — " + a.title) + '<small>' + esc(a.doc) + '</small></a>';
      }).join("") : '<div class="result">Ничего не найдено</div>';
    }).catch(function () { box.innerHTML = '<div class="result">Не удалось выполнить поиск</div>'; });
  }
  function bind() {
    document.querySelectorAll("[data-action=theme]").forEach(function (b) {
      b.onclick = function () { state.theme = state.theme === "dark" ? "light" : "dark"; localStorage.setItem("wiki-theme", state.theme); document.documentElement.dataset.theme = state.theme; };
    });
    document.querySelectorAll("[data-action=menu]").forEach(function (b) {
      b.onclick = function () {
        var nav = document.querySelector(".nav");
        if (nav) nav.classList.toggle("open");
      };
    });
    document.querySelectorAll("[data-search]").forEach(function (input) { input.oninput = function () { state.query = input.value; showResults(input); }; });
    var form = document.querySelector("[data-upload]");
    if (form) form.onsubmit = function (e) { e.preventDefault(); var out = form.querySelector("[data-upload-result]"); out.textContent = "Загрузка…"; fetch(api + "/admin/kb/upload", {method:"POST", body:new FormData(form)}).then(function (r) { return r.json().then(function (x) { return {ok:r.ok,x:x}; }); }).then(function (r) { out.textContent = r.ok ? "Готово" : "Ошибка: " + (r.x.detail || "не удалось загрузить"); }).catch(function () { out.textContent = "Нет связи с сервером"; }); };
    var reviewForm = document.querySelector("[data-review]");
    if (reviewForm) reviewForm.onsubmit = function (e) { e.preventDefault(); var out = reviewForm.querySelector("[data-review-result]"); out.textContent = "Проверка…"; fetch(api + "/documents/review", {method:"POST", body:new FormData(reviewForm)}).then(function (r) { return r.json().then(function (x) { return {ok:r.ok,x:x}; }); }).then(function (r) { if (!r.ok) { out.textContent = "Ошибка: " + (r.x.detail || "не удалось проверить"); return; } out.textContent = "Соответствие: " + r.x.summary.compliance_percent + "%"; }).catch(function () { out.textContent = "Нет связи с сервером"; }); };
    var templateBox = document.querySelector("[data-templates]");
    if (templateBox) fetch(api + "/templates").then(function (r) { return r.json(); }).then(function (items) { templateBox.innerHTML = items.map(function (a) { return '<div class="card"><span class="eyebrow">Версия ' + esc(a.version) + '</span><h3>' + esc(a.title) + '</h3><p>' + esc(a.description) + '</p><button class="btn" data-template="' + esc(a.id) + '">Начать заполнение</button></div>'; }).join(""); templateBox.querySelectorAll("[data-template]").forEach(function (b) { b.onclick = function () { if (window.__docWidget) window.__docWidget.open(); }; }); });
    var versionsBox = document.querySelector("[data-versions]");
    if (versionsBox) fetch(api + "/kb/documents").then(function (r) { return r.json(); }).then(function (items) { versionsBox.innerHTML = items.map(function (a) { return '<div class="card"><span class="eyebrow">' + esc(a.status === "active" ? "Активная версия" : "Архив") + '</span><h3>' + esc(a.doc) + '</h3><p>Версия ' + esc(a.version) + '</p></div>'; }).join(""); });
    document.documentElement.dataset.theme = state.theme;
  }
  function loadArticles() { fetch(api + "/kb/articles").then(function (r) { return r.json(); }).then(function (items) { state.articles = items; render(); }).catch(function () { render(); }); }
  window.addEventListener("hashchange", render); window.addEventListener("DOMContentLoaded", loadArticles); loadArticles();
}());

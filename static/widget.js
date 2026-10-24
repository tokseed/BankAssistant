/*!
 * Doc widget — встраиваемый чат для автозаполнения документов.
 * Подключение:
 *   <script src="https://ВАШ-ДОМЕН/static/widget.js" async></script>
 * Необязательные атрибуты тега script:
 *   data-api="https://api.example.com"  адрес API (по умолчанию — откуда загружен скрипт)
 *   data-title="Документы"              заголовок окна
 *   data-color="#0f5c5c"                акцентный цвет
 *   data-position="left"                сторона экрана (по умолчанию right)
 *   data-template="memo"                включить сразу заполнение шаблона
 *   data-token="..."                    токен авторизации от портала (роль сотрудника)
 */
(function () {
  'use strict';
  if (window.__docWidget) return;

  var script = document.currentScript;
  var d = (script && script.dataset) || {};
  var API = (d.api || (script && script.src ? new URL(script.src).origin : '')).replace(/\/$/, '');
  var TITLE = d.title || 'Помощник по регламентам';
  var COLOR = /^#[0-9a-f]{3,8}$/i.test(d.color || '') ? d.color : '#0f5c5c';
  var SIDE = d.position === 'left' ? 'left' : 'right';
  var TEMPLATE = d.template || null;
  var TOKEN = d.token || null;

  var CSS = '\
:host{all:initial}\
*{box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}\
.launcher{position:fixed;bottom:20px;' + SIDE + ':20px;width:56px;height:56px;border:0;border-radius:12px;\
background:' + COLOR + ';color:#fff;cursor:pointer;display:grid;place-items:center;\
box-shadow:0 6px 18px rgba(0,0,0,.25);z-index:2147483000}\
.launcher:focus-visible,.send:focus-visible,.chip:focus-visible,.close:focus-visible,.dl:focus-visible{outline:3px solid #ffbf47;outline-offset:2px}\
.panel{position:fixed;bottom:88px;' + SIDE + ':20px;width:372px;height:min(580px,calc(100vh - 110px));\
background:#fff;color:#1c2024;border:1px solid #cfd4d9;border-radius:12px;\
box-shadow:0 14px 40px rgba(0,0,0,.25);display:flex;flex-direction:column;overflow:hidden;z-index:2147483000}\
.panel[hidden]{display:none}\
header{background:' + COLOR + ';color:#fff;padding:12px 14px;display:flex;align-items:center;justify-content:space-between}\
header h2{margin:0;font-size:15px;font-weight:600;line-height:1.3}\
.close{background:none;border:0;color:#fff;font-size:22px;line-height:1;cursor:pointer;padding:2px 6px;border-radius:6px}\
.bar{height:3px;background:#e4e8ec}\
.bar i{display:block;height:100%;width:0;background:' + COLOR + ';transition:width .25s}\
.log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;font-size:14.5px;line-height:1.45}\
.bot{border-left:2px solid ' + COLOR + ';padding:1px 0 1px 10px;max-width:94%;white-space:pre-wrap;overflow-wrap:anywhere}\
.me{align-self:flex-end;background:' + COLOR + ';color:#fff;padding:8px 12px;border-radius:12px 12px 2px 12px;max-width:85%;overflow-wrap:anywhere}\
.err{color:#a4161a}\
.chips{display:flex;flex-wrap:wrap;gap:8px}\
.chip{background:#fff;color:' + COLOR + ';border:1.5px solid ' + COLOR + ';border-radius:8px;padding:7px 11px;font-size:13.5px;cursor:pointer}\
.chip:hover{background:' + COLOR + ';color:#fff}\
.chip:disabled{opacity:.5;cursor:default}\
.dl{display:flex;align-items:center;gap:10px;text-decoration:none;color:#1c2024;border:1.5px solid ' + COLOR + ';\
border-radius:4px 14px 4px 4px;padding:10px 12px;font-size:14px;font-weight:600}\
.dl:hover{background:#f1f6f6}\
.dl svg{flex:none;color:' + COLOR + '}\
.src{border:1px solid #d5dade;border-radius:6px;font-size:13px;max-width:94%}\
.src summary{cursor:pointer;padding:6px 10px;color:#38434b;font-weight:600}\
.src summary:focus-visible{outline:3px solid #ffbf47}\
.src ul{list-style:none;margin:0;padding:0 10px 8px}\
.src li{padding:7px 0;border-top:1px solid #eceff1}\
.src b{display:block}\
.src .rel{display:inline-block;margin-left:6px;padding:0 6px;border-radius:4px;background:#e6f0f0;color:#0b3d3d;font-weight:600}\
.src p{margin:3px 0 0;color:#4a555d}\
.typing{display:flex;gap:4px;padding:6px 0 6px 12px}\
.typing i{width:6px;height:6px;border-radius:50%;background:#8a9399;animation:b 1s infinite}\
.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.3s}\
@keyframes b{0%,60%,100%{opacity:.3}30%{opacity:1}}\
form{display:flex;gap:8px;padding:10px 12px;border-top:1px solid #e4e8ec;align-items:center}\
input{flex:1;border:0;border-bottom:1.5px solid #8a9399;padding:8px 2px;font-size:15px;background:transparent;color:inherit;border-radius:0}\
input:focus{outline:0;border-bottom-color:' + COLOR + '}\
.send{background:' + COLOR + ';color:#fff;border:0;border-radius:8px;padding:9px 14px;font-size:14px;cursor:pointer}\
@media (max-width:480px){.panel{inset:0;width:100%;height:100%;border-radius:0;border:0}}\
@media (prefers-reduced-motion:reduce){.typing i{animation:none;opacity:.6}.bar i{transition:none}}';

  var ICON_DOC = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/></svg>';

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text; // только textContent: данные пользователя не интерпретируются как HTML
    return n;
  }

  var host = el('div', { id: 'doc-widget-root' });
  var root = host.attachShadow({ mode: 'open' });
  root.appendChild(el('style', null, CSS));

  var launcher = el('button', { class: 'launcher', type: 'button', 'aria-label': 'Открыть чат: ' + TITLE, 'aria-expanded': 'false' });
  launcher.innerHTML = ICON_DOC;

  var panel = el('section', { class: 'panel', role: 'dialog', 'aria-label': TITLE });
  panel.hidden = true;
  var header = el('header');
  header.appendChild(el('h2', null, TITLE));
  var closeBtn = el('button', { class: 'close', type: 'button', 'aria-label': 'Закрыть чат' }, '×');
  header.appendChild(closeBtn);
  var bar = el('div', { class: 'bar' });
  var barFill = el('i');
  bar.appendChild(barFill);
  var log = el('div', { class: 'log', 'aria-live': 'polite' });
  var form = el('form');
  var input = el('input', { type: 'text', placeholder: 'Вопрос или ответ', 'aria-label': 'Ваше сообщение', maxlength: '500', autocomplete: 'off' });
  var send = el('button', { class: 'send', type: 'submit' }, 'Отправить');
  form.appendChild(input);
  form.appendChild(send);
  [header, bar, log, form].forEach(function (n) { panel.appendChild(n); });
  root.appendChild(launcher);
  root.appendChild(panel);

  var sid = null;
  var started = false;
  var busy = false;
  var chipBox = null;

  function scroll() { log.scrollTop = log.scrollHeight; }

  function clearChips() {
    if (chipBox) { chipBox.remove(); chipBox = null; }
  }

  function addBot(text, isError) {
    log.appendChild(el('div', { class: 'bot' + (isError ? ' err' : '') }, text));
    scroll();
  }

  function addMe(text) {
    log.appendChild(el('div', { class: 'me' }, text));
    scroll();
  }

  function addChips(options) {
    clearChips();
    chipBox = el('div', { class: 'chips' });
    options.forEach(function (o) {
      var b = el('button', { class: 'chip', type: 'button' }, o);
      b.addEventListener('click', function () { submit(o); });
      chipBox.appendChild(b);
    });
    log.appendChild(chipBox);
    scroll();
  }

  function addDownload(url) {
    // Скачиваем через fetch, чтобы передать токен авторизации (обычная ссылка заголовок не отправит)
    var btn = el('button', { class: 'dl', type: 'button' });
    btn.style.cssText = 'background:#fff;cursor:pointer;font-family:inherit;text-align:left';
    btn.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 11l5 5 5-5M5 20h14"/></svg>';
    btn.appendChild(el('span', null, 'Скачать черновик (.docx)'));
    btn.addEventListener('click', function () {
      fetch(API + url, { headers: authHeaders({}) })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          var m = /filename\*=utf-8''([^;]+)/i.exec(r.headers.get('Content-Disposition') || '');
          return r.blob().then(function (blob) { return { blob: blob, name: m ? decodeURIComponent(m[1]) : 'document.docx' }; });
        })
        .then(function (f) {
          var a = el('a', { href: URL.createObjectURL(f.blob), download: f.name });
          root.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 10000);
        })
        .catch(function () { addBot('Не удалось скачать файл: срок хранения мог истечь. Сформируйте документ заново.', true); });
    });
    log.appendChild(btn);
    scroll();
  }

  function addSources(list) {
    var box = el('details', { class: 'src' });
    box.appendChild(el('summary', null, 'Источники в инструкции (' + list.length + ')'));
    var ul = el('ul');
    list.forEach(function (x) {
      var li = el('li');
      var t = el('b', null, 'п. ' + x.point + ', ' + x.title);
      t.appendChild(el('span', { class: 'rel', title: 'Насколько пункт совпал с вашим вопросом' }, x.relevance + '%'));
      li.appendChild(t);
      li.appendChild(el('span', null, x.doc + ', версия ' + x.version));
      li.appendChild(el('p', null, x.snippet));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    log.appendChild(box);
    scroll();
  }

  function setTyping(on) {
    var t = log.querySelector('.typing');
    if (on && !t) {
      t = el('div', { class: 'typing', 'aria-label': 'Печатает' });
      t.innerHTML = '<i></i><i></i><i></i>';
      log.appendChild(t);
      scroll();
    } else if (!on && t) {
      t.remove();
    }
  }

  function authHeaders(h) {
    if (TOKEN) h['Authorization'] = 'Bearer ' + TOKEN;
    return h;
  }

  function post(path, body) {
    return fetch(API + path, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        return { ok: r.ok, status: r.status, data: data };
      });
    });
  }

  function render(reply) {
    sid = reply.session_id || sid;
    (reply.messages || []).forEach(function (m) { addBot(m); });
    if (reply.sources && reply.sources.length) addSources(reply.sources);
    if (reply.download_url) addDownload(reply.download_url);
    if (reply.options && reply.options.length) addChips(reply.options);
    var p = reply.progress;
    barFill.style.width = p && p.total ? Math.round((p.current / p.total) * 100) + '%' : '0';
  }

  function fail(text) {
    setTyping(false);
    addBot(text, true);
  }

  function startSession() {
    busy = true;
    setTyping(true);
    post('/api/sessions', TEMPLATE ? { template_id: TEMPLATE } : {})
      .then(function (r) {
        busy = false;
        setTyping(false);
        if (!r.ok) return fail((r.data && r.data.detail) || 'Не удалось начать диалог. Попробуйте позже.');
        render(r.data);
      })
      .catch(function () { busy = false; fail('Нет связи с сервером. Проверьте интернет и откройте чат снова.'); started = false; });
  }

  function submit(text) {
    text = (text || '').trim();
    if (!text || busy || !sid) return;
    busy = true;
    clearChips();
    addMe(text);
    input.value = '';
    setTyping(true);
    post('/api/sessions/' + sid + '/messages', { text: text })
      .then(function (r) {
        busy = false;
        setTyping(false);
        if (r.status === 404) {
          sid = null;
          addBot('Сессия истекла. Начнём заново.', true);
          return startSession();
        }
        if (!r.ok) return fail('Не получилось отправить ответ. Попробуйте ещё раз.');
        render(r.data);
        input.focus();
      })
      .catch(function () { busy = false; fail('Нет связи с сервером. Повторите отправку.'); });
  }

  function open() {
    panel.hidden = false;
    launcher.setAttribute('aria-expanded', 'true');
    if (!started) { started = true; startSession(); }
    setTimeout(function () { input.focus(); }, 0);
  }

  function close() {
    panel.hidden = true;
    launcher.setAttribute('aria-expanded', 'false');
    launcher.focus();
  }

  launcher.addEventListener('click', function () { panel.hidden ? open() : close(); });
  closeBtn.addEventListener('click', close);
  panel.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  form.addEventListener('submit', function (e) { e.preventDefault(); submit(input.value); });

  window.__docWidget = { open: open, close: close };
  window.DocWidget = window.__docWidget;

  function mount() { document.body.appendChild(host); }
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
})();

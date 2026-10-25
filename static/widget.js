/*!
 * Doc widget — встраиваемый чат для автозаполнения документов.
 * Подключение:
 *   <script src="https://ВАШ-ДОМЕН/static/widget.js" async></script>
 * Необязательные атрибуты тега script:
 *   data-api="https://api.example.com"  адрес API (по умолчанию — откуда загружен скрипт)
 *   data-title="Документы"              заголовок окна
 *   data-color="#0f5c5c"                акцентный цвет
 *   data-theme="light|dark|medium"      цветовая схема
 *   data-open="true"                    открыть чат сразу
 *   data-layout="full"                  полноэкранный режим демо
 *   data-position="left"                сторона экрана (по умолчанию right)
 *   data-template="memo"                включить сразу заполнение шаблона
 *   data-token="..."                    токен авторизации от портала (роль сотрудника)
 */
(function () {
  'use strict';
  if (window.__docWidget) return;

  var script = document.currentScript;
  var d = (script && script.dataset) || {};
  var SCRIPT_URL = script && script.src ? new URL(script.src, window.location.href) : null;
  var API = (d.api
    ? new URL(d.api, window.location.href).origin
    : (SCRIPT_URL ? SCRIPT_URL.origin : window.location.origin)
  ).replace(/\/+$/, '');

  function init(savedConfig) {
  savedConfig = savedConfig || {};
  var TITLE = d.title || savedConfig.title || 'Банк';
  var AUTO_OPEN = /^(1|true|yes)$/i.test(d.open || d.autostart || '');
  var FULL_LAYOUT = d.layout === 'full';
  // Тема страницы не должна влиять на тему виджета. Для виджета используются
  // только data-theme конкретного embed-кода или настройки чат-бота.
  var selectedTheme = d.theme || savedConfig.theme || 'medium';
  var THEME = /^(light|dark|medium)$/i.test(selectedTheme) ? selectedTheme.toLowerCase() : 'medium';
  var PALETTE = {
    light:  { bg: '#F8F6F0', panel: '#F8F6F0', surface: '#FFFFFF', text: '#17211D', muted: '#59645E', border: '#DEDCD4', bubble: '#ECEAE2', accent: '#24483F', accentText: '#FFFFFF' },
    dark:   { bg: '#0D1117', panel: '#161B22', surface: '#21262D', text: '#F0F6FC', muted: '#A7B1BC', border: '#30363D', bubble: '#21262D', accent: '#8FD3B8', accentText: '#0D1117' },
    medium: { bg: '#1E293B', panel: '#283548', surface: '#34445A', text: '#F4F7FA', muted: '#B8C3D0', border: '#4A5B70', bubble: '#34445A', accent: '#B7D7C9', accentText: '#1E293B' }
  }[THEME];
  var configColor = savedConfig.color || '';
  var COLOR = /^#[0-9a-f]{3,8}$/i.test(d.color || '') ? d.color : (/^#[0-9a-f]{6}$/i.test(configColor) ? configColor : PALETTE.accent);
  var SIDE = d.position === 'left' ? 'left' : 'right';
  var TEMPLATE = d.template || null;
  var TOKEN = d.token || null;

  var CSS = '\
:host{all:initial;--pi-bg:' + PALETTE.bg + ';--pi-panel:' + PALETTE.panel + ';--pi-surface:' + PALETTE.surface + ';--pi-text:' + PALETTE.text + ';--pi-muted:' + PALETTE.muted + ';--pi-border:' + PALETTE.border + ';--pi-bubble:' + PALETTE.bubble + '}\
*{box-sizing:border-box;font-family:"SFMono-Regular","Roboto Mono",ui-monospace,Menlo,Consolas,monospace}\
.launcher{position:fixed;bottom:calc(20px + env(safe-area-inset-bottom));' + SIDE + ':20px;width:58px;height:58px;border:1px solid ' + COLOR + ';border-radius:8px;\
background:var(--pi-panel);color:' + COLOR + ';cursor:pointer;display:grid;place-items:center;\
box-shadow:0 8px 24px rgba(0,0,0,.28);z-index:2147483000}\
.launcher:focus-visible,.send:focus-visible,.attach:focus-visible,.chip:focus-visible,.close:focus-visible,.settings:focus-visible,.dl:focus-visible{outline:3px solid #ffbf47;outline-offset:2px}\
.panel{position:fixed;bottom:84px;' + SIDE + ':20px;width:380px;height:min(560px,calc(100vh - 108px));\
background:var(--pi-panel);color:var(--pi-text);border:1px solid var(--pi-border);border-radius:8px;\
box-shadow:0 18px 50px rgba(0,0,0,.35);display:flex;flex-direction:column;overflow:hidden;z-index:2147483000}\
.panel[hidden]{display:none}\
.panel.full{top:28px;bottom:28px;left:50%;right:auto;transform:translateX(-50%);width:min(560px,calc(100vw - 56px));height:auto;border-radius:8px}\
header{background:var(--pi-panel);color:var(--pi-text);padding:14px 18px 13px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--pi-border)}\
.header-copy{min-width:0}\
header h2{margin:0;font-size:17px;font-weight:700;letter-spacing:.02em;line-height:1.3}\
.header-actions{display:flex;align-items:center;gap:8px}.close,.settings{background:transparent;border:1px solid var(--pi-border);color:var(--pi-text);line-height:1;cursor:pointer;border-radius:4px}.close{font-size:21px;padding:1px 7px}.settings{width:38px;height:38px;display:grid;place-items:center;padding:0}.settings:hover,.close:hover{border-color:' + COLOR + ';color:' + COLOR + '}\
.bar{height:3px;background:var(--pi-border)}\
.bar i{display:block;height:100%;width:0;background:' + COLOR + ';transition:width .25s}\
.log{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:12px;font-size:14px;line-height:1.5}\
.bot-wrap{max-width:94%}.bot{background:var(--pi-bubble);color:var(--pi-text);border-left:2px solid ' + COLOR + ';padding:12px 14px;max-width:100%;white-space:pre-wrap;overflow-wrap:anywhere;border-radius:2px}\
.feedback{display:flex;align-items:center;gap:6px;margin-top:5px;color:var(--pi-muted);font-size:11px}.feedback button{background:transparent;border:1px solid var(--pi-border);color:var(--pi-muted);border-radius:3px;padding:2px 7px;cursor:pointer}.feedback button:hover{border-color:' + COLOR + ';color:' + COLOR + '}.feedback button:disabled{opacity:.55;cursor:default}\
.me{align-self:flex-end;background:var(--pi-surface);color:var(--pi-text);border:1px solid var(--pi-border);padding:11px 14px;border-radius:3px;max-width:85%;overflow-wrap:anywhere}\
.err{color:#a4161a}\
.chips{display:flex;flex-wrap:wrap;gap:8px}\
.chip{background:var(--pi-surface);color:' + COLOR + ';border:1px solid ' + COLOR + ';border-radius:3px;padding:8px 11px;font-size:13px;cursor:pointer}\
.chip:hover{background:' + COLOR + ';color:#fff}\
.chip:disabled{opacity:.5;cursor:default}\
.doc-types{display:flex;flex-wrap:wrap;gap:6px;padding:0 0 2px}\
.doc-chip{background:var(--pi-surface);color:' + COLOR + ';border:1px solid ' + COLOR + ';border-radius:3px;padding:6px 9px;font-size:12px;cursor:pointer}\
.doc-chip:hover{background:' + COLOR + ';color:#fff}\
.dl{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--pi-text);border:1px solid ' + COLOR + ';\
border-radius:3px;padding:10px 12px;font-size:13px;font-weight:600}\
.dl:hover{background:var(--pi-bubble)}\
.dl svg{flex:none;color:' + COLOR + '}\
.src{border:1px solid var(--pi-border);border-radius:12px;font-size:13px;max-width:94%}\
.src summary{cursor:pointer;padding:6px 10px;color:var(--pi-text);font-weight:600}\
.src summary:focus-visible{outline:3px solid #ffbf47}\
.src ul{list-style:none;margin:0;padding:0 10px 8px}\
.src li{padding:7px 0;border-top:1px solid var(--pi-border)}\
.src b{display:block}\
.src .rel{display:inline-block;margin-left:6px;padding:0 6px;border-radius:4px;background:var(--pi-bubble);color:var(--pi-text);font-weight:600}\
.src p{margin:3px 0 0;color:var(--pi-muted)}\
.review{border:1px solid var(--pi-border);border-radius:8px;font-size:13px;max-width:94%}\
.review summary{cursor:pointer;padding:8px 10px;color:var(--pi-text);font-weight:600}\
.review-body{padding:0 10px 10px}.review-stat{color:var(--pi-muted);margin-bottom:8px}.review-list{list-style:none;margin:0;padding:0}.review-list li{padding:7px 0;border-top:1px solid var(--pi-border)}\
.review-list .ok{color:' + COLOR + '}.review-list .bad{color:#ff8a8a}.review-list small{display:block;color:var(--pi-muted);margin-top:3px}.review-note{margin-top:10px;color:var(--pi-muted);white-space:pre-wrap}\
.typing{display:flex;gap:4px;padding:6px 0 6px 12px}\
.typing i{width:6px;height:6px;border-radius:50%;background:#8a9399;animation:b 1s infinite}\
.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.3s}\
@keyframes b{0%,60%,100%{opacity:.3}30%{opacity:1}}\
form{display:flex;gap:8px;padding:12px 14px;border-top:1px solid var(--pi-border);align-items:center;background:var(--pi-panel)}\
input{flex:1;min-width:0;border:0;border-top:1px solid var(--pi-border);border-bottom:1px solid var(--pi-border);border-radius:0;padding:11px 8px;font-size:14px;background:transparent;color:var(--pi-text)}\
input:focus{outline:0;border-top-color:' + COLOR + ';border-bottom-color:' + COLOR + '}\
.file-input{display:none}\
.attach{width:38px;height:38px;display:grid;place-items:center;background:transparent;color:' + COLOR + ';border:1px solid var(--pi-border);border-radius:4px;cursor:pointer;flex:none}\
.attach:hover{background:var(--pi-surface)}\
.attach:disabled{opacity:.5;cursor:default}\
.send{width:40px;height:38px;background:' + COLOR + ';color:#fff;border:0;border-radius:4px;padding:0;font-size:22px;font-weight:700;cursor:pointer}\
@media (max-width:640px){\
.panel:not(.full){inset:10px 10px 78px 10px;width:auto;height:auto;border-radius:8px}\
.panel.full{top:10px;right:10px;bottom:10px;left:10px;width:auto;height:auto}\
.log{padding:14px;font-size:13px;gap:10px}\
header{padding:12px 14px}header h2{font-size:15px}\
form{padding:10px 12px;padding-bottom:calc(10px + env(safe-area-inset-bottom))}\
input{font-size:16px}\
}\
@media (max-width:480px){.panel{inset:0!important;width:100%!important;height:100vh!important;height:100dvh!important;border-radius:0;border:0}.panel.full{transform:none}}\
@media (prefers-reduced-motion:reduce){.typing i{animation:none;opacity:.6}.bar i{transition:none}}';

  var ICON_DOC = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/></svg>';

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text; // только textContent: данные пользователя не интерпретируются как HTML
    return n;
  }

  var host = el('div', { id: 'doc-widget-root' });
  host.setAttribute('data-theme', THEME);
  var root = host.attachShadow({ mode: 'open' });
  root.appendChild(el('style', null, CSS));

  var launcher = el('button', { class: 'launcher', type: 'button', 'aria-label': 'Открыть чат: ' + TITLE, 'aria-expanded': 'false' });
  launcher.innerHTML = ICON_DOC;

  var panel = el('section', {
    class: 'panel' + (FULL_LAYOUT ? ' full' : ''),
    role: 'dialog',
    'aria-label': TITLE
  });
  panel.hidden = true;
  var header = el('header');
  var headerCopy = el('div', { class: 'header-copy' });
  headerCopy.appendChild(el('h2', null, TITLE));
  header.appendChild(headerCopy);
  var headerActions = el('div', { class: 'header-actions' });
  var settingsBtn = el('button', { class: 'settings', type: 'button', 'aria-label': 'Открыть настройки', title: 'Настройки' });
  settingsBtn.innerHTML = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.12 2.12-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V20.3h-3v-.08A1.7 1.7 0 0 0 10.68 18.66a1.7 1.7 0 0 0-1.88.34l-.06.06-2.12-2.12.06-.06A1.7 1.7 0 0 0 7.02 15a1.7 1.7 0 0 0-1.56-1.03h-.08v-3h.08A1.7 1.7 0 0 0 7.02 9.94a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.12-2.12.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56V4.6h3v.08a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06L19.8 8l-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.03h.08v3h-.08A1.7 1.7 0 0 0 19.4 15Z"/></svg>';
  var closeBtn = el('button', { class: 'close', type: 'button', 'aria-label': 'Закрыть чат' }, '×');
  settingsBtn.addEventListener('click', function () { window.location.assign(API + '/settings'); });
  headerActions.appendChild(settingsBtn);
  headerActions.appendChild(closeBtn);
  header.appendChild(headerActions);
  var bar = el('div', { class: 'bar' });
  var barFill = el('i');
  bar.appendChild(barFill);
  var log = el('div', { class: 'log', 'aria-live': 'polite' });
  var form = el('form');
  var input = el('input', { type: 'text', placeholder: 'Вопрос или ответ', 'aria-label': 'Ваше сообщение', maxlength: '500', autocomplete: 'off' });
  var fileInput = el('input', { class: 'file-input', type: 'file', accept: '.pdf,.docx,.txt', multiple: 'multiple', 'aria-label': 'Прикрепить документы' });
  var attach = el('button', { class: 'attach', type: 'button', 'aria-label': 'Прикрепить документы', title: 'PDF, DOCX или TXT' });
  attach.innerHTML = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.4 11.6-8.8 8.8a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 1 1-2.8-2.8l8.5-8.5"/></svg>';
  var send = el('button', { class: 'send', type: 'submit', 'aria-label': 'Отправить', title: 'Отправить' }, '→');
  attach.addEventListener('click', function () { if (!busy) fileInput.click(); });
  form.appendChild(fileInput);
  form.appendChild(attach);
  form.appendChild(input);
  form.appendChild(send);
  [header, bar, log, form].forEach(function (n) { panel.appendChild(n); });
  root.appendChild(launcher);
  root.appendChild(panel);

  var sid = null;
  var started = false;
  var busy = false;
  var chipBox = null;
  var documentTypesShown = false;
  var feedbackId = null;

  function scroll() { log.scrollTop = log.scrollHeight; }

  function clearChips() {
    if (chipBox) { chipBox.remove(); chipBox = null; }
  }

  function addBot(text, isError, withFeedback) {
    var wrap = el('div', { class: 'bot-wrap' });
    wrap.appendChild(el('div', { class: 'bot' + (isError ? ' err' : '') }, text));
    if (withFeedback && !isError) addFeedback(wrap);
    log.appendChild(wrap);
    scroll();
  }

  function addFeedback(parent) {
    var box = el('div', { class: 'feedback' });
    box.appendChild(el('span', null, 'Ответ полезен?'));
    var yes = el('button', { type: 'button', title: 'Полезный ответ' }, 'Да');
    var no = el('button', { type: 'button', title: 'Ответ нужно исправить' }, 'Нет');
    function send(rating, correction) {
      yes.disabled = true; no.disabled = true;
      post('/api/sessions/' + sid + '/feedback', {
        rating: rating,
        correction: correction || '',
        answer_id: feedbackId || ''
      }).then(function (result) {
        if (!result.ok) throw new Error((result.data && result.data.detail) || 'Не удалось сохранить оценку');
        box.textContent = result.data.message || 'Спасибо, оценка сохранена.';
      }).catch(function () {
        yes.disabled = false; no.disabled = false;
        box.appendChild(el('span', null, ' Не удалось сохранить.'));
      });
    }
    yes.addEventListener('click', function () { send('positive'); });
    no.addEventListener('click', function () {
      var correction = window.prompt('Что было неверно? Напишите правильный вариант или уточнение:');
      if (correction === null) correction = '';
      send('negative', correction);
    });
    box.appendChild(yes);
    box.appendChild(no);
    parent.appendChild(box);
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

  function addDocumentTypes(types) {
    if (documentTypesShown || !types || !types.length) return;
    documentTypesShown = true;
    var box = el('div', { class: 'doc-types', 'aria-label': 'Виды документов' });
    types.forEach(function (type) {
      var b = el('button', { class: 'doc-chip', type: 'button', title: type.description || '' }, type.title);
      b.disabled = type.available === false;
      if (b.disabled) b.title = 'Недоступно для вашей роли';
      b.addEventListener('click', function () {
        if (!b.disabled) submit('Подготовить: ' + type.title);
      });
      box.appendChild(b);
    });
    log.appendChild(box);
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
      if (x.id) {
        var link = el('a', { href: API + '/wiki#/article/' + encodeURIComponent(x.id), target: '_blank', rel: 'noopener' }, 'Открыть пункт в базе знаний');
        li.appendChild(link);
      }
      ul.appendChild(li);
    });
    box.appendChild(ul);
    log.appendChild(box);
    scroll();
  }

  function addReview(review) {
    if (!review || !review.summary) return;
    var summary = review.summary;
    var box = el('details', { class: 'review' });
    box.open = true;
    box.appendChild(el('summary', null, 'Показать полный анализ документа'));
    var body = el('div', { class: 'review-body' });
    body.appendChild(el('div', { class: 'review-stat' },
      'Соответствие: ' + summary.compliance_percent + '% · разделов: ' + summary.sections +
      ' · найдено оснований: ' + summary.matched + ' · без основания: ' + summary.unmatched));
    var list = el('ul', { class: 'review-list' });
    (review.checks || []).forEach(function (item) {
      var source = item.source;
      var li = el('li', { class: item.status === 'matched' ? 'ok' : 'bad' });
      li.appendChild(el('strong', null,
        (item.status === 'matched' ? '✓ ' : '× ') +
        (item.draft_point ? 'п. ' + item.draft_point : 'Фрагмент') +
        ' · ' + item.relevance + '%'));
      li.appendChild(el('small', null, item.text));
      if (source && source.id) {
        li.appendChild(el('a', {
          href: API + '/wiki#/article/' + encodeURIComponent(source.id),
          target: '_blank',
          rel: 'noopener'
        }, 'Открыть основание в базе знаний'));
      }
      list.appendChild(li);
    });
    body.appendChild(list);
    if (review.recommendations && review.recommendations.length) {
      body.appendChild(el('div', { class: 'review-note' },
        'Рекомендации:\n' + review.recommendations.join('\n')));
    }
    box.appendChild(body);
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
    feedbackId = reply.feedback_id || null;
    (reply.messages || []).forEach(function (m, index) {
      addBot(m, false, Boolean(reply.feedback_available) && index === 0);
    });
    addDocumentTypes(reply.document_types);
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

  function uploadFiles(files) {
    if (!files || !files.length || busy || !sid) return;
    busy = true;
    clearChips();
    setTyping(true);
    var list = Array.prototype.slice.call(files);
    var upload = list.reduce(function (promise, file) {
      return promise.then(function () {
        addMe('📎 ' + file.name);
        var data = new FormData();
        data.append('file', file);
        return fetch(API + '/api/sessions/' + sid + '/files', {
          method: 'POST',
          headers: authHeaders({}),
          body: data
        }).then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (body) {
            if (!r.ok) throw new Error(body.detail || 'Не удалось загрузить файл');
            (body.messages || ['Файл загружен.']).forEach(function (m) { addBot(m); });
            addReview(body.review);
          });
        });
      });
    }, Promise.resolve()).catch(function (e) {
      addBot(e.message || 'Не удалось загрузить файл.', true);
    }).then(function () {
      busy = false;
      setTyping(false);
      fileInput.value = '';
      input.focus();
    });
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
  fileInput.addEventListener('change', function () { uploadFiles(fileInput.files); });

  window.__docWidget = { open: open, close: close };
  window.DocWidget = window.__docWidget;

  function mount() {
    document.body.appendChild(host);
    if (AUTO_OPEN) setTimeout(open, 0);
  }
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
  }

  fetch(API + '/api/widget-config', { credentials: 'omit' })
    .then(function (r) { return r.ok ? r.json() : {}; })
    .catch(function () { return {}; })
    .then(init);
})();

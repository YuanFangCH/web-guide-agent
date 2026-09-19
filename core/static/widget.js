(function () {
  "use strict";

  if (window.GuideAgentWidget) {
    return;
  }

  var script = document.currentScript;
  var apiBase = (script && script.dataset.agentBase) || "/api/guide-agent";
  var tourBase = (script && script.dataset.agentTourBase) || "/api/tours";
  var TOUR_INVITE_KEY = "cwt-tour-invite-seen";
  var TOUR_STATE_KEY = "cwt-tour-state";
  var state = {
    open: false,
    busy: false,
    conversationId: null,
    sections: [],
    currentAnchor: "",
    unread: 0,
    abortController: null,
    sequenceRunning: false,
    sequencePaused: false,
    sequenceIndex: 0,
    sequenceSections: [],
    drag: null,
    dragged: false,
    panelDrag: null,
    panelRestore: null,
    tour: {
      active: false,
      route: null,
      index: 0,
      mode: "page",
      paused: false,
      timer: null,
      remaining: 0,
      questionPause: false,
      inviteOpen: false,
      routes: {},
      loading: null
    }
  };

  function mediaMarkup(name, className, loading) {
    void name;
    void loading;
    return (
      '<span class="cwt-media ' +
      className +
      '" aria-hidden="true"><span class="cwt-media-fallback">WA</span></span>'
    );
  }

  function avatarMarkup(className, loading) {
    return mediaMarkup("avatar.webp", "cwt-avatar-media " + className, loading);
  }

  function bustMarkup(className, loading) {
    void loading;
    return (
      '<span class="cwt-head-bust ' +
      className +
      '" aria-hidden="true"><span>WA</span></span>'
    );
  }

  function smokeMarkup() {
    return '<span class="cwt-smoke" aria-hidden="true"></span>';
  }

  function featureMarkup(name) {
    void name;
    return (
      '<span class="cwt-feature-visual" aria-hidden="true"><span>WA</span></span>'
    );
  }

  function injectStyles() {
    if (document.getElementById("cwt-widget-style")) {
      return;
    }
    var style = document.createElement("style");
    style.id = "cwt-widget-style";
    style.textContent = [
      ".cwt-root{--cwt-font:15px;--cwt-font-small:12px;--cwt-font-title:17px;--cwt-image-height:270px;--cwt-avatar-size:42px;--cwt-message-avatar-size:28px;--cwt-feature-size:112px;--cwt-head-bust-height:106px;--cwt-head-bust-right:88px;--cwt-tour-thumb-width:84px;--cwt-tour-thumb-height:56px;position:fixed;right:20px;bottom:20px;z-index:2147483000;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;color:#0f172a}",
      ".cwt-avatar{position:relative;display:flex;align-items:center;gap:9px;border:1px solid rgba(255,255,255,.35);border-radius:999px;padding:7px 14px 7px 8px;background:#0a2745;color:#fff;box-shadow:0 14px 36px rgba(10,39,69,.28);cursor:grab;font-size:14px;font-weight:700;touch-action:none;user-select:none;transition:box-shadow .22s ease,transform .22s ease}",
      ".cwt-avatar:hover,.cwt-avatar:focus-visible{box-shadow:0 18px 42px rgba(10,39,69,.36);outline:none}",
      ".cwt-avatar:active{cursor:grabbing;transform:scale(.97)}",
      ".cwt-media{position:relative;display:grid;flex:none;place-items:center;overflow:hidden;border-radius:50%;background:rgba(255,255,255,.1);color:currentColor}",
      ".cwt-media img{position:absolute;inset:0;z-index:1;width:100%;height:100%;object-fit:cover;transition:transform .24s ease,filter .24s ease}",
      ".cwt-media img[hidden]{display:none}",
      ".cwt-media-fallback{display:grid;width:100%;height:100%;place-items:center}",
      ".cwt-media-fallback svg{width:56%;height:56%;flex:none}",
      ".cwt-avatar-media{width:var(--cwt-avatar-size);height:var(--cwt-avatar-size);border:1px solid rgba(240,198,106,.62);box-shadow:inset 0 0 0 1px rgba(255,255,255,.12)}",
      ".cwt-avatar-media::after{content:'';position:absolute;inset:-5px;border:2px solid #f0c66a;border-radius:50%;opacity:0;pointer-events:none}",
      ".cwt-avatar:hover .cwt-avatar-media img,.cwt-avatar:focus-visible .cwt-avatar-media img{transform:translateY(-2px) rotate(-1.5deg) scale(1.05)}",
      ".cwt-avatar:active .cwt-avatar-media img{transform:scale(.94)}",
      ".cwt-smoke{position:absolute;top:-29px;left:25px;z-index:2;width:34px;height:46px;pointer-events:none;opacity:.78;transform-origin:50% 100%}",
      ".cwt-smoke img{width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 3px 5px rgba(10,39,69,.18))}",
      ".cwt-unread{position:absolute;top:-7px;right:-7px;min-width:19px;height:19px;padding:0 5px;border-radius:999px;background:#d92d20;color:#fff;font-size:11px;line-height:19px;text-align:center}",
      ".cwt-unread[hidden]{display:none}",
      ".cwt-panel{position:fixed;right:20px;bottom:20px;width:min(660px,calc(100vw - 32px));height:min(860px,calc(100vh - 32px));min-width:360px;min-height:520px;max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);display:flex;flex-direction:column;overflow:hidden;border:1px solid rgba(15,23,42,.16);border-radius:16px;background:#fff;box-shadow:0 24px 70px rgba(15,23,42,.28);font-size:var(--cwt-font);transform-origin:calc(100% - 36px) calc(100% - 36px)}",
      ".cwt-panel[hidden]{display:none}",
      ".cwt-panel.cwt-panel-in{animation:cwt-panel-in .28s cubic-bezier(.2,.85,.3,1) both}",
      ".cwt-head{position:relative;display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:96px;padding:12px 14px;background:#0a2745;color:#fff}",
      ".cwt-head-bust{position:absolute;right:var(--cwt-head-bust-right);top:0;z-index:1;display:block;height:var(--cwt-head-bust-height);pointer-events:none}",
      ".cwt-head-bust[hidden]{display:none}",
      ".cwt-head-bust img{display:block;width:auto;height:100%;max-width:none;object-fit:contain;object-position:center bottom;filter:drop-shadow(0 8px 12px rgba(0,0,0,.24))}",
      ".cwt-title{position:relative;z-index:2;display:flex;flex:1 1 auto;align-items:center;gap:8px;min-width:0;max-width:calc(100% - 150px);font-weight:800}",
      ".cwt-title>div{flex:1 1 auto;min-width:0}",
      ".cwt-title small{display:block;margin-top:2px;color:rgba(255,255,255,.65);font-size:var(--cwt-font-small);font-weight:500}",
      ".cwt-head-actions{position:relative;z-index:3;display:flex;flex:none;align-items:center;gap:4px}",
      ".cwt-icon-btn{display:grid;width:30px;height:30px;place-items:center;border:0;border-radius:8px;background:rgba(255,255,255,.1);color:#fff;cursor:pointer}",
      ".cwt-chapter{padding:18px 14px 9px;border-bottom:1px solid #e2e8f0;background:#fff}",
      ".cwt-select{width:100%;border:1px solid #cbd5e1;border-radius:9px;padding:8px 10px;background:#fff;font:inherit;font-size:calc(var(--cwt-font) - 1px)}",
      ".cwt-tour{display:grid;gap:10px;padding:12px 14px;border-bottom:1px solid #d9e2ec;background:#f0f6fb}",
      ".cwt-tour[hidden]{display:none}",
      ".cwt-tour-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}",
      ".cwt-tour-title{min-width:0}",
      ".cwt-tour-title small{display:block;margin-bottom:2px;color:#005bac;font-size:var(--cwt-font-small);font-weight:700}",
      ".cwt-tour-title strong{display:block;font-size:var(--cwt-font-title);line-height:1.35}",
      ".cwt-tour-count{min-width:54px;text-align:right;color:#0a2745}",
      ".cwt-tour-count strong{display:block;font-size:calc(var(--cwt-font-title) + 3px);line-height:1}",
      ".cwt-tour-count small{font-size:var(--cwt-font-small);color:#64748b}",
      ".cwt-tour-progress{height:4px;overflow:hidden;border-radius:999px;background:#dbe7f1}",
      ".cwt-tour-progress span{display:block;height:100%;border-radius:inherit;background:#c8901f;transition:width .25s ease}",
      ".cwt-tour-actions{display:flex;flex-wrap:wrap;gap:6px}",
      ".cwt-tour-btn{border:1px solid #b8c9d8;border-radius:8px;background:#fff;color:#0a2745;padding:7px 10px;font-size:var(--cwt-font-small);font-weight:700;cursor:pointer}",
      ".cwt-tour-btn:hover{border-color:#005bac;color:#005bac}",
      ".cwt-tour-btn.primary{border-color:#005bac;background:#005bac;color:#fff}",
      ".cwt-tour-btn.danger{border-color:#e4b7b2;color:#a72a1e}",
      ".cwt-tour-image{display:block;width:100%;max-height:var(--cwt-image-height);object-fit:cover;border-radius:10px;border:1px solid #cbd5e1;background:#fff}",
      ".cwt-tour-caption{margin-top:6px;color:#64748b;font-size:var(--cwt-font-small);line-height:1.5}",
      ".cwt-tour-page #cwt-tour-card{display:grid;grid-template-columns:var(--cwt-tour-thumb-width) minmax(0,1fr);align-items:center;gap:10px;min-height:var(--cwt-tour-thumb-height)}",
      ".cwt-tour-page .cwt-tour-image{width:var(--cwt-tour-thumb-width);height:var(--cwt-tour-thumb-height);max-height:none;border-radius:8px}",
      ".cwt-tour-page .cwt-tour-caption{margin-top:0}",
      ".cwt-tour-complete{display:grid;gap:8px;padding:12px;border:1px solid #e2c879;border-radius:10px;background:#fffaf0}",
      ".cwt-tour-links{display:flex;flex-wrap:wrap;gap:6px}",
      ".cwt-tour-link{display:inline-flex;border:1px solid #cbd5e1;border-radius:999px;background:#fff;color:#005bac;padding:5px 9px;text-decoration:none;font-size:var(--cwt-font-small)}",
      ".cwt-messages{flex:1;overflow:auto;padding:16px;background:#f8fafc}",
      ".cwt-message{max-width:90%;margin:0 0 12px;padding:10px 12px;border-radius:12px;font-size:var(--cwt-font);line-height:1.65;word-break:break-word;overflow-wrap:anywhere}",
      ".cwt-message.user{margin-left:auto;background:#005bac;color:#fff;border-bottom-right-radius:4px;white-space:pre-wrap}",
      ".cwt-message.assistant{display:grid;grid-template-columns:var(--cwt-message-avatar-size) minmax(0,1fr);gap:8px;max-width:100%;padding:0;border:0;background:transparent}",
      ".cwt-message-avatar{position:relative;width:var(--cwt-message-avatar-size);height:var(--cwt-message-avatar-size);margin-top:3px}",
      ".cwt-message-avatar .cwt-avatar-media{width:100%;height:100%;border-color:#d6e0ea;box-shadow:0 3px 10px rgba(10,39,69,.12)}",
      ".cwt-message-content{min-width:0;padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;border-bottom-left-radius:4px;background:#fff}",
      ".cwt-message-feature .cwt-message-content{display:flow-root}",
      ".cwt-feature-visual{float:right;width:var(--cwt-feature-size);margin:0 0 8px 12px;pointer-events:none}",
      ".cwt-feature-visual img{display:block;width:100%;height:auto;filter:drop-shadow(0 8px 12px rgba(10,39,69,.12))}",
      ".cwt-message p{margin:0 0 8px}.cwt-message p:last-child{margin-bottom:0}",
      ".cwt-message h1,.cwt-message h2,.cwt-message h3{margin:10px 0 6px;font-size:var(--cwt-font-title);line-height:1.4}",
      ".cwt-message ul,.cwt-message ol{margin:6px 0 8px;padding-left:20px}",
      ".cwt-message code{padding:1px 4px;border-radius:4px;background:#eef2f7;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:var(--cwt-font-small)}",
      ".cwt-message pre{margin:8px 0;padding:10px;overflow:auto;border-radius:8px;background:#0f172a;color:#e2e8f0}",
      ".cwt-message pre code{padding:0;background:transparent;color:inherit}",
      ".cwt-message a{color:#005bac;text-decoration:underline}",
      ".cwt-sources{display:none!important}",
      ".cwt-tools{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 12px 9px;background:#fff;color:#64748b;font-size:var(--cwt-font-small)}",
      ".cwt-link{border:0;background:transparent;color:#005bac;cursor:pointer;font-size:var(--cwt-font-small);padding:0}",
      ".cwt-link:disabled{color:#94a3b8;cursor:not-allowed}",
      ".cwt-compose{display:flex;gap:8px;padding:12px;border-top:1px solid #e2e8f0;background:#fff}",
      ".cwt-input{min-width:0;flex:1;resize:none;border:1px solid #cbd5e1;border-radius:10px;padding:10px;font:inherit;font-size:var(--cwt-font);outline:none}",
      ".cwt-input:focus{border-color:#005bac;box-shadow:0 0 0 3px rgba(0,91,172,.12)}",
      ".cwt-send{border:0;border-radius:10px;padding:0 14px;background:#005bac;color:#fff;font-weight:700;cursor:pointer}",
      ".cwt-send:disabled{opacity:.5;cursor:not-allowed}",
      ".cwt-resize{position:absolute;right:2px;bottom:2px;width:22px;height:22px;border:0;background:transparent;cursor:nwse-resize;touch-action:none;opacity:.55}",
      ".cwt-resize::after{content:'';position:absolute;right:5px;bottom:5px;width:8px;height:8px;border-right:2px solid #64748b;border-bottom:2px solid #64748b}",
      ".cwt-resize:hover{opacity:1}",
      ".cwt-panel.maximized .cwt-resize{display:none}",
      ".cwt-highlight{outline:3px solid #f0c66a!important;outline-offset:4px!important;border-radius:6px!important;transition:outline-color .2s ease}",
      ".cwt-root.cwt-busy .cwt-avatar-media img,.cwt-root.cwt-busy .cwt-head-bust img{animation:cwt-breathe 1.8s ease-in-out infinite}",
      ".cwt-root.cwt-busy .cwt-smoke{animation:cwt-smoke 3.2s ease-in-out infinite}",
      ".cwt-root.cwt-replied .cwt-avatar-media::after{animation:cwt-reply-ring .72s ease-out both}",
      "@keyframes cwt-panel-in{from{opacity:0;transform:translate(18px,22px) scale(.94)}to{opacity:1;transform:translate(0,0) scale(1)}}",
      "@keyframes cwt-breathe{0%,100%{transform:translateY(0) rotate(0) scale(1)}50%{transform:translateY(-2px) rotate(-1deg) scale(1.035)}}",
      "@keyframes cwt-smoke{0%,100%{transform:translate(0,2px) scale(.96);opacity:.58}50%{transform:translate(5px,-5px) scale(1.04);opacity:.9}}",
      "@keyframes cwt-reply-ring{0%{opacity:.9;transform:scale(.84)}100%{opacity:0;transform:scale(1.35)}}",
      "@media(max-width:640px){.cwt-root{right:8px;bottom:8px;--cwt-avatar-size:40px;--cwt-message-avatar-size:26px;--cwt-feature-size:78px;--cwt-head-bust-height:84px;--cwt-head-bust-right:60px;--cwt-tour-thumb-width:72px;--cwt-tour-thumb-height:48px}.cwt-panel{left:8px;right:8px;top:8px;bottom:8px;width:auto;height:auto;min-width:0;min-height:0;max-width:none;max-height:none;border-radius:12px}.cwt-head{min-height:82px}.cwt-title{max-width:calc(100% - 112px)}.cwt-chapter{padding-top:14px}.cwt-title small{display:none}.cwt-resize{display:none}.cwt-maximize{display:none}.cwt-panel{--cwt-font:14px;--cwt-font-small:12px;--cwt-font-title:16px;--cwt-image-height:230px}.cwt-feature-visual{margin-left:8px}.cwt-smoke{left:22px}}",
      "@media(prefers-reduced-motion:reduce){.cwt-avatar,.cwt-media img,.cwt-smoke,.cwt-panel,.cwt-avatar-media::after{animation:none!important;transition:none!important}}"
    ].join("");
    document.head.appendChild(style);
  }

  function icon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/><path d="M8 9h8M8 13h5"/></svg>';
  }

  function maximizeIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/><path d="M8 9h8M8 13h5"/></svg>';
  }

  function normalizeText(value) {
    return String(value || "")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t]+/g, " ")
      .replace(/\s*\n\s*/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function hash(value) {
    var result = 2166136261;
    for (var index = 0; index < value.length; index += 1) {
      result ^= value.charCodeAt(index);
      result = Math.imul(result, 16777619);
    }
    return (result >>> 0).toString(16);
  }

  function pageKey() {
    var explicit = document.querySelector("[data-agent-page-key]");
    if (explicit && explicit.dataset.agentPageKey) {
      return explicit.dataset.agentPageKey;
    }
    return hash(location.origin + location.pathname + location.search);
  }

  function ensureAnchor(element, index) {
    var anchor =
      element.dataset.agentAnchor ||
      element.id ||
      "cwt-section-" + (index + 1);
    element.dataset.agentAnchor = anchor;
    return anchor;
  }

  function headingText(element) {
    var heading = element.querySelector("h1,h2,h3");
    return heading
      ? normalizeText(heading.textContent)
      : normalizeText(element.dataset.agentTitle || "");
  }

  function extractSections() {
    var main = document.querySelector("main") || document.body;
    var explicit = Array.prototype.slice.call(
      main.querySelectorAll("[data-agent-section]")
    );
    if (explicit.length) {
      return explicit
        .map(function (element, index) {
          return {
            anchor: ensureAnchor(element, index),
            selector: element.id ? "#" + element.id : "",
            heading: headingText(element),
            text: normalizeText(element.innerText || element.textContent)
          };
        })
        .filter(function (section) {
          return section.text;
        });
    }

    var headings = Array.prototype.slice.call(
      main.querySelectorAll("h1,h2,h3")
    );
    if (headings.length) {
      return headings
        .map(function (heading, index) {
          var text = [];
          var sibling = heading.nextElementSibling;
          while (sibling && !/^H[1-3]$/.test(sibling.tagName)) {
            var value = normalizeText(sibling.innerText || sibling.textContent);
            if (value) {
              text.push(value);
            }
            sibling = sibling.nextElementSibling;
          }
          return {
            anchor: ensureAnchor(heading, index),
            selector: heading.id ? "#" + heading.id : "",
            heading: normalizeText(heading.textContent),
            text: text.join("\n")
          };
        })
        .filter(function (section) {
          return section.heading || section.text;
        });
    }

    var containers = Array.prototype.slice.call(
      main.querySelectorAll("section,article")
    );
    if (containers.length > 1) {
      return containers
        .map(function (element, index) {
          return {
            anchor: ensureAnchor(element, index),
            selector: element.id ? "#" + element.id : "",
            heading: headingText(element),
            text: normalizeText(element.innerText || element.textContent)
          };
        })
        .filter(function (section) {
          return section.text;
        });
    }

    var text = normalizeText(main.innerText || main.textContent);
    var chunks = [];
    for (var start = 0; start < text.length && chunks.length < 24; start += 1200) {
      var value = text.slice(start, start + 1200).trim();
      if (value) {
        chunks.push({
          anchor: "cwt-section-" + (chunks.length + 1),
          selector: "",
          heading: "",
          text: value
        });
      }
    }
    return chunks;
  }

  function pageContext() {
    var sections = extractSections();
    state.sections = sections;
    return {
      pageKey: pageKey(),
      contentHash: hash(
        (document.title || "") +
          sections
            .map(function (section) {
              return section.anchor + section.heading + section.text;
            })
            .join("")
      ),
      url: location.href,
      title: document.title,
      text: normalizeText(
        (document.querySelector("main") || document.body).innerText || ""
      ).slice(0, 30000),
      sections: sections.slice(0, 50).map(function (section) {
        return {
          anchor: section.anchor,
          selector: section.selector,
          heading: section.heading,
          text: section.text.slice(0, 1500)
        };
      }),
      currentAnchor: state.currentAnchor
    };
  }

  function tourContextPayload() {
    if (!state.tour.active || !state.tour.route) {
      return null;
    }
    var stop = currentStop();
    var stops = state.tour.route.stops || [];
    return {
      id: state.tour.route.id,
      title: state.tour.route.title,
      stepIndex: state.tour.index,
      stepCount: stops.length,
      mode: state.tour.mode,
      paused: state.tour.paused,
      currentStep: stop
        ? {
            id: stop.id,
            title: stop.title,
            eyebrow: stop.eyebrow,
            narration: stop.narration,
            href: stop.href,
            heading: stop.heading || ""
          }
        : null,
      previousStep: stops[state.tour.index - 1]
        ? stops[state.tour.index - 1].title
        : null,
      nextStep: stops[state.tour.index + 1]
        ? stops[state.tour.index + 1].title
        : null
    };
  }

  function cachePage() {
    var context = pageContext();
    return fetch(apiBase + "/page/cache", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(context)
    }).catch(function () {});
  }

  function scrollToAnchor(anchor) {
    if (!anchor) {
      return null;
    }
    var target =
      document.querySelector(
        '[data-agent-anchor="' + CSS.escape(anchor) + '"]'
      ) || document.getElementById(anchor);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      state.currentAnchor = anchor;
    }
    return target;
  }

  function targetForStop(stop) {
    if (!stop) {
      return null;
    }
    if (stop.anchor) {
      var anchored =
        document.querySelector(
          '[data-agent-anchor="' + CSS.escape(stop.anchor) + '"]'
        ) || document.getElementById(stop.anchor);
      if (anchored) {
        return anchored;
      }
    }
    var wanted = normalizeText(stop.heading || stop.title || "")
      .replace(/\s+/g, "")
      .toLowerCase();
    if (!wanted) {
      return null;
    }
    var candidates = Array.prototype.slice.call(
      document.querySelectorAll("main h1,main h2,main h3,[data-agent-section]")
    );
    for (var index = 0; index < candidates.length; index += 1) {
      var candidate = candidates[index];
      var value = normalizeText(
        candidate.dataset.agentTitle ||
          candidate.textContent ||
          ""
      )
        .replace(/\s+/g, "")
        .toLowerCase();
      if (value === wanted || value.indexOf(wanted) >= 0 || wanted.indexOf(value) >= 0) {
        return candidate;
      }
    }
    if (!stop.heading && !stop.anchor) {
      window.scrollTo({ top: 0, behavior: "smooth" });
      return document.querySelector("main") || document.body;
    }
    return null;
  }

  function scrollToStop(stop) {
    var target = targetForStop(stop);
    if (!target) {
      return null;
    }
    if (!target.dataset.agentAnchor) {
      ensureAnchor(target, 0);
    }
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    state.currentAnchor = target.dataset.agentAnchor || "";
    updateChapterSelect();
    target.classList.add("cwt-highlight");
    window.setTimeout(function () {
      target.classList.remove("cwt-highlight");
    }, 6000);
    return target;
  }

  function waitForStop(stop, timeoutMs) {
    return new Promise(function (resolve) {
      var startedAt = Date.now();
      var timer = window.setInterval(function () {
        var target = scrollToStop(stop);
        if (target || Date.now() - startedAt >= (timeoutMs || 8000)) {
          window.clearInterval(timer);
          resolve(target || null);
        }
      }, 180);
    });
  }

  function highlight(anchor) {
    var target = scrollToAnchor(anchor);
    if (!target) {
      return;
    }
    target.classList.add("cwt-highlight");
    window.setTimeout(function () {
      target.classList.remove("cwt-highlight");
    }, 6000);
  }

  function navigateInPage(url) {
    var host = window.GuideAgentHost;
    if (host && typeof host.navigate === "function") {
      return host.navigate(url);
    }
    try {
      var parsed = new URL(url, location.href);
      if (parsed.origin === location.origin) {
        location.assign(parsed.href);
        return new Promise(function (resolve) {
          window.setTimeout(function () {
            resolve(true);
          }, 800);
        });
      }
      window.open(parsed.href, "_blank", "noopener,noreferrer");
      return Promise.resolve(false);
    } catch {
      return Promise.resolve(false);
    }
  }

  function openLink(url) {
    try {
      var parsed = new URL(url, location.href);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return;
      }
      if (parsed.origin === location.origin) {
        navigateInPage(parsed.href).then(function () {
          pageContext();
          updateChapterSelect();
        });
      } else {
        window.open(parsed.href, "_blank", "noopener,noreferrer");
      }
    } catch {
      return;
    }
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderInline(value) {
    var text = escapeHtml(value);
    text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, label, url) {
      try {
        var parsed = new URL(url, location.href);
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
          return label;
        }
        var sameOrigin = parsed.origin === location.origin;
        return (
          '<a href="' +
          escapeHtml(parsed.href) +
          '"' +
          (sameOrigin
            ? ""
            : ' target="_blank" rel="noopener noreferrer"') +
          ">" +
          label +
          "</a>"
        );
      } catch {
        return label;
      }
    });
    return text;
  }

  function renderMarkdown(value) {
    var lines = String(value || "").split(/\r?\n/);
    var html = [];
    var inCode = false;
    var code = [];
    var listType = "";
    var paragraph = [];

    function flushParagraph() {
      if (paragraph.length) {
        html.push("<p>" + renderInline(paragraph.join(" ")) + "</p>");
        paragraph = [];
      }
    }
    function closeList() {
      if (listType) {
        html.push("</" + listType + ">");
        listType = "";
      }
    }

    lines.forEach(function (line) {
      if (line.indexOf("```") === 0) {
        flushParagraph();
        closeList();
        if (inCode) {
          html.push("<pre><code>" + escapeHtml(code.join("\n")) + "</code></pre>");
          code = [];
          inCode = false;
        } else {
          inCode = true;
        }
        return;
      }
      if (inCode) {
        code.push(line);
        return;
      }
      var heading = /^(#{1,3})\s+(.+)$/.exec(line);
      if (heading) {
        flushParagraph();
        closeList();
        var level = heading[1].length;
        html.push(
          "<h" + level + ">" + renderInline(heading[2]) + "</h" + level + ">"
        );
        return;
      }
      var unordered = /^\s*[-*]\s+(.+)$/.exec(line);
      var ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
      if (unordered || ordered) {
        flushParagraph();
        var nextType = unordered ? "ul" : "ol";
        if (listType !== nextType) {
          closeList();
          listType = nextType;
          html.push("<" + listType + ">");
        }
        html.push("<li>" + renderInline((unordered || ordered)[1]) + "</li>");
        return;
      }
      closeList();
      if (!line.trim()) {
        flushParagraph();
      } else {
        paragraph.push(line.trim());
      }
    });
    if (inCode) {
      html.push("<pre><code>" + escapeHtml(code.join("\n")) + "</code></pre>");
    }
    flushParagraph();
    closeList();
    return html.join("");
  }

  function addMessage(role, text) {
    var messages = document.getElementById("cwt-messages");
    var element = document.createElement("div");
    element.className = "cwt-message " + role;
    if (role === "assistant") {
      element.innerHTML =
        '<span class="cwt-message-avatar">' +
        avatarMarkup("cwt-message-avatar-media", "lazy") +
        "</span>" +
        '<div class="cwt-message-content">' +
        renderMarkdown(text) +
        "</div>";
    } else {
      element.textContent = text;
    }
    messages.appendChild(element);
    messages.scrollTop = messages.scrollHeight;
    return element;
  }

  function addFeatureVisual(element, name) {
    var content = element && element.querySelector(".cwt-message-content");
    if (!content) {
      return;
    }
    element.classList.add("cwt-message-feature");
    content.insertAdjacentHTML("afterbegin", featureMarkup(name));
  }

  function flashReply() {
    var root = document.querySelector(".cwt-root");
    if (!root) {
      return;
    }
    root.classList.remove("cwt-replied");
    void root.offsetWidth;
    root.classList.add("cwt-replied");
    window.setTimeout(function () {
      root.classList.remove("cwt-replied");
    }, 760);
  }

  function setBusy(value) {
    state.busy = value;
    var root = document.querySelector(".cwt-root");
    if (root) {
      root.classList.toggle("cwt-busy", value);
    }
    document.getElementById("cwt-send").disabled = value;
    document.getElementById("cwt-stop").hidden = !value;
  }

  function updateChapterSelect() {
    var select = document.getElementById("cwt-chapter");
    select.innerHTML = '<option value="">跟随当前页面</option>';
    state.sections.forEach(function (section) {
      var option = document.createElement("option");
      option.value = section.anchor;
      option.textContent = section.heading || "未命名章节";
      select.appendChild(option);
    });
    select.value = state.currentAnchor || "";
  }

  function currentStop() {
    if (!state.tour.route || !state.tour.route.stops) {
      return null;
    }
    return state.tour.route.stops[state.tour.index] || null;
  }

  function saveTourState() {
    if (!state.tour.active || !state.tour.route) {
      sessionStorage.removeItem(TOUR_STATE_KEY);
      return;
    }
    sessionStorage.setItem(
      TOUR_STATE_KEY,
      JSON.stringify({
        routeId: state.tour.route.id,
        mode: state.tour.mode,
        index: state.tour.index,
        paused: state.tour.paused
      })
    );
  }

  function loadTour(routeId) {
    if (state.tour.routes[routeId]) {
      return Promise.resolve(state.tour.routes[routeId]);
    }
    if (state.tour.loading && state.tour.loading.id === routeId) {
      return state.tour.loading.promise;
    }
    var request = fetch(
      tourBase + "/" + encodeURIComponent(routeId),
      { credentials: "same-origin", cache: "reload" }
    )
      .then(function (response) {
        if (!response.ok) {
          throw new Error("路线暂时不可用");
        }
        return response.json();
      })
      .then(function (route) {
        state.tour.routes[routeId] = route;
        state.tour.loading = null;
        return route;
      })
      .catch(function (error) {
        state.tour.loading = null;
        throw error;
      });
    state.tour.loading = { id: routeId, promise: request };
    return request;
  }

  function clearTourTimer() {
    if (state.tour.timer) {
      window.clearInterval(state.tour.timer);
      state.tour.timer = null;
    }
  }

  function updateTourUi() {
    var root = document.getElementById("cwt-tour");
    if (!root) {
      return;
    }
    root.hidden = !state.tour.active;
    if (!state.tour.active || !state.tour.route) {
      return;
    }
    root.classList.toggle("cwt-tour-page", state.tour.mode === "page");
    root.classList.toggle("cwt-tour-window", state.tour.mode === "window");
    var stop = currentStop();
    var total = state.tour.route.stops.length;
    document.getElementById("cwt-tour-step").textContent = stop
      ? stop.eyebrow || "第 " + (state.tour.index + 1) + " 站"
      : state.tour.route.title;
    document.getElementById("cwt-tour-name").textContent = stop
      ? stop.title
      : state.tour.route.title;
    document.getElementById("cwt-tour-total").textContent = total;
    document.getElementById("cwt-tour-index").textContent =
      state.tour.index + 1;
    document.getElementById("cwt-tour-progress-bar").style.width =
      (((state.tour.index + 1) / total) * 100).toFixed(1) + "%";
    document.getElementById("cwt-tour-count").textContent = state.tour.paused
      ? "已暂停"
      : state.tour.remaining + " 秒";
    document.getElementById("cwt-tour-pause").textContent = state.tour.paused
      ? "继续"
      : "暂停";
    document.getElementById("cwt-tour-pause").hidden = false;
    document.getElementById("cwt-tour-prev").disabled = state.tour.index <= 0;
    document.getElementById("cwt-tour-next").textContent =
      state.tour.index >= total - 1 ? "结束" : "下一站";
  }

  function renderTourStop(stop) {
    var card = document.getElementById("cwt-tour-card");
    card.innerHTML = [
      '<img class="cwt-tour-image" loading="eager" src="' +
        escapeHtml(stop.image.src) +
        '" alt="' +
        escapeHtml(stop.image.alt) +
        '">',
      '<div class="cwt-tour-caption">' +
        escapeHtml(stop.image.caption || stop.image.alt) +
        "</div>"
    ].join("");
  }

  function startCountdown() {
    clearTourTimer();
    var stop = currentStop();
    if (!stop || state.tour.paused) {
      updateTourUi();
      return;
    }
    state.tour.remaining = stop.dwellSeconds;
    updateTourUi();
    state.tour.timer = window.setInterval(function () {
      if (!state.tour.active) {
        clearTourTimer();
        return;
      }
      if (state.tour.paused) {
        return;
      }
      state.tour.remaining -= 1;
      if (state.tour.remaining <= 0) {
        clearTourTimer();
        if (state.tour.index >= state.tour.route.stops.length - 1) {
          completeTour();
        } else {
          goToTourStep(state.tour.index + 1);
        }
        return;
      }
      updateTourUi();
    }, 1000);
  }

  function pauseTour(showReturn) {
    if (!state.tour.active) {
      return;
    }
    state.tour.paused = true;
    state.tour.questionPause = Boolean(showReturn);
    clearTourTimer();
    document.getElementById("cwt-tour-return").hidden = !showReturn;
    updateTourUi();
    saveTourState();
  }

  function resumeTour() {
    if (!state.tour.active) {
      return;
    }
    state.tour.paused = false;
    state.tour.questionPause = false;
    document.getElementById("cwt-tour-return").hidden = true;
    var stop = currentStop();
    var run = function () {
      state.tour.remaining = stop.dwellSeconds;
      startCountdown();
      saveTourState();
    };
    if (state.tour.mode === "page" && stop) {
      Promise.resolve(navigateInPage(stop.href))
        .then(function () {
          return waitForStop(stop, 8000);
        })
        .then(function () {
          pageContext();
          updateChapterSelect();
          run();
        });
    } else {
      run();
    }
  }

  function goToTourStep(index) {
    if (!state.tour.active || !state.tour.route) {
      return;
    }
    var total = state.tour.route.stops.length;
    if (index >= total) {
      completeTour();
      return;
    }
    if (index < 0) {
      return;
    }
    clearTourTimer();
    state.tour.index = index;
    state.tour.paused = false;
    state.tour.questionPause = false;
    document.getElementById("cwt-tour-return").hidden = true;
    var stop = currentStop();
    renderTourStop(stop);
    updateTourUi();
    saveTourState();
    addMessage(
      "assistant",
      "**" + stop.eyebrow + " · " + stop.title + "**\n\n" + stop.narration
    );

    var start = function () {
      startCountdown();
    };
    if (state.tour.mode === "page") {
      Promise.resolve(navigateInPage(stop.href))
        .then(function () {
          return waitForStop(stop, 8000);
        })
        .then(function (target) {
          if (!target && stop.heading) {
            addMessage(
              "assistant",
              "这一段暂未找到页面定位，但讲解仍会继续。你可以直接问网页讲解助手当前页面内容。"
            );
          }
          pageContext();
          updateChapterSelect();
          start();
        })
        .catch(function () {
          start();
        });
    } else {
      start();
    }
  }

  function completeTour() {
    clearTourTimer();
    var route = state.tour.route;
    state.tour.active = false;
    state.tour.paused = true;
    document.getElementById("cwt-tour-return").hidden = true;
    sessionStorage.removeItem(TOUR_STATE_KEY);
    updateTourUi();
    var element = addMessage("assistant", route.completion);
    addFeatureVisual(element, "bust.webp");
    var content = element.querySelector(".cwt-message-content");
    var links = route.extensions || [];
    if (links.length) {
      content.insertAdjacentHTML(
        "beforeend",
        '<div class="cwt-tour-complete"><strong>继续探索</strong><div class="cwt-tour-links">' +
          links
            .map(function (item) {
              return (
                '<a class="cwt-tour-link" target="_blank" rel="noopener noreferrer" href="' +
                escapeHtml(item.href) +
                '">' +
                escapeHtml(item.title) +
                "</a>"
              );
            })
            .join("") +
          "</div></div>"
      );
    }
  }

  function stopTour() {
    clearTourTimer();
    state.tour.active = false;
    state.tour.paused = false;
    state.tour.questionPause = false;
    state.tour.index = 0;
    sessionStorage.removeItem(TOUR_STATE_KEY);
    document.getElementById("cwt-tour-return").hidden = true;
    updateTourUi();
    addMessage("assistant", "已退出参观路线。你仍可以继续问当前页面或站内资料。");
  }

  function showTourInvite(routeId) {
    setOpen(true);
    clearTourTimer();
    if (state.tour.active) {
      stopTour();
    }
    loadTour(routeId)
      .then(function (route) {
        state.tour.inviteOpen = true;
        var element = addMessage(
          "assistant",
          "**" + route.title + "**\n\n" + route.invitation
        );
        addFeatureVisual(element, "bust.webp");
        var content = element.querySelector(".cwt-message-content");
        [
          { label: "网页参观（推荐）", mode: "page", primary: true },
          { label: "窗口参观", mode: "window", primary: false },
          { label: "暂不参观", mode: "", primary: false }
        ].forEach(function (option) {
          var button = document.createElement("button");
          button.type = "button";
          button.className =
            "cwt-tour-btn" + (option.primary ? " primary" : "");
          button.textContent = option.label;
          button.style.margin = "8px 6px 0 0";
          button.addEventListener("click", function () {
            if (!option.mode) {
              sessionStorage.setItem(TOUR_INVITE_KEY, "1");
              element
                .querySelectorAll(".cwt-tour-btn")
                .forEach(function (item) {
                  item.disabled = true;
                });
              addMessage("assistant", "好的，不开始参观。你可以随时问我当前页面或站内资料。");
              return;
            }
            element
              .querySelectorAll(".cwt-tour-btn")
              .forEach(function (item) {
                item.disabled = true;
              });
            startTour(routeId, option.mode);
          });
          content.appendChild(button);
        });
      })
      .catch(function (error) {
        addMessage(
          "assistant",
          "参观路线暂时无法加载：" + error.message
        );
      });
  }

  function startTour(routeId, mode) {
    loadTour(routeId)
      .then(function (route) {
        clearTourTimer();
        state.tour.inviteOpen = false;
        state.tour.active = true;
        state.tour.route = route;
        state.tour.mode = mode === "window" ? "window" : "page";
        state.tour.index = 0;
        state.tour.paused = false;
        state.tour.questionPause = false;
        sessionStorage.setItem(TOUR_INVITE_KEY, "1");
        addMessage(
          "assistant",
          "参观开始。当前模式：" +
            (state.tour.mode === "page" ? "网页参观" : "窗口参观") +
            "。共 " +
            route.stops.length +
            " 站，随时可以暂停、提问或退出。"
        );
        goToTourStep(0);
      })
      .catch(function (error) {
        addMessage("assistant", "参观路线无法启动：" + error.message);
      });
  }

  function restoreTour() {
    var saved = null;
    try {
      saved = JSON.parse(sessionStorage.getItem(TOUR_STATE_KEY) || "null");
    } catch {
      saved = null;
    }
    if (!saved || !saved.routeId) {
      return;
    }
    loadTour(saved.routeId)
      .then(function (route) {
        state.tour.route = route;
        state.tour.index = Math.max(
          0,
          Math.min(Number(saved.index) || 0, route.stops.length - 1)
        );
        state.tour.mode = saved.mode === "window" ? "window" : "page";
        state.tour.active = true;
        state.tour.paused = true;
        document.getElementById("cwt-tour-return").hidden = false;
        renderTourStop(currentStop());
        updateTourUi();
        addMessage(
          "assistant",
          "上次参观停留在第 " +
            (state.tour.index + 1) +
            " 站。点击“回到参观”继续，或直接问我当前页面。"
        );
      })
      .catch(function () {
        sessionStorage.removeItem(TOUR_STATE_KEY);
      });
  }

  var trackTimer = null;
  function trackCurrentSection() {
    var elements = Array.prototype.slice.call(
      document.querySelectorAll("[data-agent-anchor]")
    );
    var current = "";
    elements.forEach(function (element) {
      var rect = element.getBoundingClientRect();
      if (rect.top <= window.innerHeight * 0.35 && rect.bottom >= 0) {
        current = element.dataset.agentAnchor || "";
      }
    });
    if (current && current !== state.currentAnchor) {
      state.currentAnchor = current;
      updateChapterSelect();
    }
  }

  function handleAction(action) {
    if (!action || !action.type) {
      return;
    }
    if (action.type === "scroll") {
      scrollToAnchor(action.anchor);
    } else if (action.type === "highlight") {
      highlight(action.anchor);
    } else if (action.type === "open_link") {
      openLink(action.url);
    } else if (action.type === "sequential_explain") {
      startSequentialExplain(action.sections || state.sections);
    }
  }

  function parseSseBlock(block) {
    var eventName = "message";
    var dataLines = [];
    block.split(/\r?\n/).forEach(function (line) {
      if (line.indexOf("event:") === 0) {
        eventName = line.slice(6).trim();
      } else if (line.indexOf("data:") === 0) {
        dataLines.push(line.slice(5).trim());
      }
    });
    var data = {};
    try {
      data = dataLines.length ? JSON.parse(dataLines.join("\n")) : {};
    } catch {
      data = { text: dataLines.join("\n") };
    }
    return { event: eventName, data: data };
  }

  async function sendQuestion(question, mode, force) {
    if (!question || (state.busy && !force)) {
      return;
    }
    var tourQuestion =
      state.tour.active && (mode || "chat") === "chat";
    if (tourQuestion) {
      pauseTour(true);
    }
    setBusy(true);
    addMessage("user", question);
    var answerElement = addMessage("assistant", "");
    var answerContent = answerElement.querySelector(".cwt-message-content");
    var answer = "";
    state.abortController = new AbortController();

    try {
      var response = await fetch(apiBase + "/chat/stream", {
        method: "POST",
        credentials: "include",
        signal: state.abortController.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question,
          mode: mode || "chat",
          conversationId: state.conversationId,
          pageContext: pageContext(),
          tourContext: tourContextPayload()
        })
      });
      if (!response.ok || !response.body) {
        throw new Error("Agent request failed: " + response.status);
      }
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      while (true) {
        var result = await reader.read();
        if (result.done) {
          break;
        }
        buffer += decoder.decode(result.value, { stream: true });
        var boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          var event = parseSseBlock(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          if (event.event === "meta" && event.data.conversationId) {
            state.conversationId = event.data.conversationId;
          } else if (event.event === "token" && event.data.text) {
            answer += event.data.text;
            answerContent.innerHTML = renderMarkdown(answer);
            if (!state.open) {
              state.unread += 1;
              updateUnread();
            }
            document.getElementById("cwt-messages").scrollTop =
              document.getElementById("cwt-messages").scrollHeight;
          } else if (event.event === "actions") {
            (event.data.items || []).forEach(handleAction);
          } else if (event.event === "error") {
            throw new Error(event.data.message || "Agent error");
          }
          boundary = buffer.indexOf("\n\n");
        }
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        answerContent.innerHTML = renderMarkdown(
          "网页讲解助手暂时无法回答：" + error.message
        );
      }
    } finally {
      state.abortController = null;
      if (answer) {
        flashReply();
      }
      setBusy(false);
    }
    return answer;
  }

  function updateUnread() {
    var badge = document.getElementById("cwt-unread");
    badge.hidden = state.unread <= 0;
    badge.textContent = state.unread > 9 ? "9+" : String(state.unread);
  }

  function wait(ms) {
    return new Promise(function (resolve) {
      var elapsed = 0;
      var timer = window.setInterval(function () {
        if (!state.sequenceRunning) {
          window.clearInterval(timer);
          resolve();
          return;
        }
        if (!state.sequencePaused) {
          elapsed += 200;
        }
        if (elapsed >= ms) {
          window.clearInterval(timer);
          resolve();
        }
      }, 200);
    });
  }

  async function startSequentialExplain(sections) {
    if (state.sequenceRunning) {
      state.sequenceRunning = false;
      state.sequencePaused = false;
      document.getElementById("cwt-sequence").textContent = "逐段讲解";
      document.getElementById("cwt-pause").hidden = true;
      return;
    }
    state.sequenceSections = (sections || state.sections).slice(0, 30);
    if (!state.sequenceSections.length) {
      addMessage("assistant", "当前页面没有可逐段讲解的章节。");
      return;
    }
    state.sequenceRunning = true;
    state.sequencePaused = false;
    state.sequenceIndex = 0;
    document.getElementById("cwt-sequence").textContent = "停止讲解";
    document.getElementById("cwt-pause").hidden = false;
    document.getElementById("cwt-pause").textContent = "暂停";
    for (var index = 0; index < state.sequenceSections.length; index += 1) {
      if (!state.sequenceRunning) {
        break;
      }
      state.sequenceIndex = index;
      var section = state.sequenceSections[index];
      highlight(section.anchor);
      await sendQuestion(
        "请用简洁中文讲解当前页面章节：" +
          (section.heading || "第 " + (index + 1) + " 段"),
        "explain",
        true
      );
      if (index < state.sequenceSections.length - 1) {
        await wait(10000);
      }
    }
    state.sequenceRunning = false;
    state.sequencePaused = false;
    document.getElementById("cwt-sequence").textContent = "逐段讲解";
    document.getElementById("cwt-pause").hidden = true;
  }

  function setOpen(value) {
    state.open = value;
    document.getElementById("cwt-avatar").hidden = value;
    var panel = document.getElementById("cwt-panel");
    panel.hidden = !value;
    panel.classList.remove("cwt-panel-in");
    if (value) {
      void panel.offsetWidth;
      panel.classList.add("cwt-panel-in");
      state.unread = 0;
      updateUnread();
      window.setTimeout(function () {
        document.getElementById("cwt-input").focus();
        updatePanelScale();
      }, 50);
    }
  }

  var PANEL_SIZE_KEY = "cwt-panel-size";

  function panelLimits() {
    return {
      minWidth: Math.min(360, window.innerWidth - 16),
      minHeight: Math.min(520, window.innerHeight - 16),
      maxWidth: Math.max(320, window.innerWidth - 16),
      maxHeight: Math.max(420, window.innerHeight - 16)
    };
  }

  function updatePanelScale() {
    var panel = document.getElementById("cwt-panel");
    var root = document.querySelector(".cwt-root");
    if (!panel || !root || panel.hidden) {
      return;
    }
    var width = panel.getBoundingClientRect().width || 560;
    var ratio = Math.max(0.95, Math.min(1.4, width / 560));
    root.style.setProperty("--cwt-font", Math.round(15 * ratio) + "px");
    root.style.setProperty(
      "--cwt-font-small",
      Math.round(12 * ratio) + "px"
    );
    root.style.setProperty(
      "--cwt-font-title",
      Math.round(17 * ratio) + "px"
    );
    root.style.setProperty(
      "--cwt-image-height",
      Math.round(270 * ratio) + "px"
    );
    root.style.setProperty(
      "--cwt-avatar-size",
      Math.round(42 * ratio) + "px"
    );
    root.style.setProperty(
      "--cwt-feature-size",
      Math.round(112 * ratio) + "px"
    );
    var compact = window.innerWidth <= 640;
    root.style.setProperty(
      "--cwt-head-bust-height",
      compact
        ? "84px"
        : Math.max(96, Math.min(126, Math.round(108 * ratio))) + "px"
    );
    root.style.setProperty(
      "--cwt-tour-thumb-width",
      compact ? "72px" : Math.round(84 * ratio) + "px"
    );
    root.style.setProperty(
      "--cwt-tour-thumb-height",
      compact ? "48px" : Math.round(56 * ratio) + "px"
    );
  }

  function applyPanelSize(width, height) {
    var panel = document.getElementById("cwt-panel");
    if (!panel || window.innerWidth <= 640) {
      return;
    }
    var limits = panelLimits();
    var finalWidth = Math.max(
      limits.minWidth,
      Math.min(limits.maxWidth, Number(width) || limits.minWidth)
    );
    var finalHeight = Math.max(
      limits.minHeight,
      Math.min(limits.maxHeight, Number(height) || limits.minHeight)
    );
    panel.style.left = "auto";
    panel.style.top = "auto";
    panel.style.right = "20px";
    panel.style.bottom = "20px";
    panel.style.width = finalWidth + "px";
    panel.style.height = finalHeight + "px";
    panel.classList.remove("maximized");
    updatePanelScale();
  }

  function savePanelSize() {
    var panel = document.getElementById("cwt-panel");
    if (!panel || window.innerWidth <= 640 || panel.classList.contains("maximized")) {
      return;
    }
    try {
      localStorage.setItem(
        PANEL_SIZE_KEY,
        JSON.stringify({
          width: Math.round(panel.getBoundingClientRect().width),
          height: Math.round(panel.getBoundingClientRect().height)
        })
      );
    } catch {
      return;
    }
  }

  function restorePanelSize() {
    if (window.innerWidth <= 640) {
      return;
    }
    var saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(PANEL_SIZE_KEY) || "null");
    } catch {
      saved = null;
    }
    if (saved && Number.isFinite(saved.width) && Number.isFinite(saved.height)) {
      applyPanelSize(saved.width, saved.height);
    }
  }

  function toggleMaximizedPanel() {
    var panel = document.getElementById("cwt-panel");
    if (!panel || window.innerWidth <= 640) {
      return;
    }
    if (panel.classList.contains("maximized")) {
      panel.classList.remove("maximized");
      var restore = state.panelRestore;
      if (restore) {
        applyPanelSize(restore.width, restore.height);
      } else {
        restorePanelSize();
      }
      state.panelRestore = null;
      return;
    }
    var rect = panel.getBoundingClientRect();
    state.panelRestore = { width: rect.width, height: rect.height };
    panel.classList.add("maximized");
    panel.style.left = "12px";
    panel.style.top = "12px";
    panel.style.right = "12px";
    panel.style.bottom = "12px";
    panel.style.width = "auto";
    panel.style.height = "auto";
    updatePanelScale();
  }

  function mountPanelResize() {
    var panel = document.getElementById("cwt-panel");
    var grip = document.getElementById("cwt-resize");
    var maximize = document.getElementById("cwt-maximize");
    if (!panel || !grip || !maximize) {
      return;
    }

    restorePanelSize();
    maximize.addEventListener("click", toggleMaximizedPanel);
    grip.addEventListener("pointerdown", function (event) {
      if (window.innerWidth <= 640) {
        return;
      }
      var rect = panel.getBoundingClientRect();
      state.panelDrag = {
        startX: event.clientX,
        startY: event.clientY,
        width: rect.width,
        height: rect.height
      };
      panel.classList.remove("maximized");
      grip.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    grip.addEventListener("pointermove", function (event) {
      if (!state.panelDrag) {
        return;
      }
      applyPanelSize(
        state.panelDrag.width + event.clientX - state.panelDrag.startX,
        state.panelDrag.height + event.clientY - state.panelDrag.startY
      );
    });
    grip.addEventListener("pointerup", function () {
      if (!state.panelDrag) {
        return;
      }
      state.panelDrag = null;
      savePanelSize();
    });
    grip.addEventListener("pointercancel", function () {
      state.panelDrag = null;
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth <= 640) {
        panel.classList.remove("maximized");
        panel.style.left = "";
        panel.style.top = "";
        panel.style.right = "";
        panel.style.bottom = "";
        panel.style.width = "";
        panel.style.height = "";
      } else if (panel.classList.contains("maximized")) {
        updatePanelScale();
      } else {
        var rect = panel.getBoundingClientRect();
        applyPanelSize(rect.width, rect.height);
      }
    });
  }

  function mountDrag() {
    var avatar = document.getElementById("cwt-avatar");
    var saved = null;
    try {
      saved = JSON.parse(localStorage.getItem("cwt-avatar-position") || "null");
    } catch {
      saved = null;
    }
    if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
      avatar.style.left = saved.left + "px";
      avatar.style.top = saved.top + "px";
      avatar.style.position = "fixed";
      avatar.style.right = "auto";
      avatar.style.bottom = "auto";
    }
    avatar.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) {
        return;
      }
      var rect = avatar.getBoundingClientRect();
      state.drag = {
        offsetX: event.clientX - rect.left,
        offsetY: event.clientY - rect.top
      };
      avatar.setPointerCapture(event.pointerId);
    });
    avatar.addEventListener("pointermove", function (event) {
      if (!state.drag) {
        return;
      }
      var left = Math.max(
        8,
        Math.min(window.innerWidth - avatar.offsetWidth - 8, event.clientX - state.drag.offsetX)
      );
      var top = Math.max(
        8,
        Math.min(window.innerHeight - avatar.offsetHeight - 8, event.clientY - state.drag.offsetY)
      );
      avatar.style.left = left + "px";
      avatar.style.top = top + "px";
      avatar.style.position = "fixed";
      avatar.style.right = "auto";
      avatar.style.bottom = "auto";
      state.dragged = true;
    });
    avatar.addEventListener("pointerup", function () {
      if (!state.drag) {
        return;
      }
      state.drag = null;
      localStorage.setItem(
        "cwt-avatar-position",
        JSON.stringify({
          left: parseFloat(avatar.style.left),
          top: parseFloat(avatar.style.top)
        })
      );
      window.setTimeout(function () {
        state.dragged = false;
      }, 200);
    });
  }

  function mount() {
    injectStyles();
    var root = document.createElement("div");
    root.className = "cwt-root";
    root.addEventListener(
      "error",
      function (event) {
        if (
          event.target &&
          event.target.matches &&
          event.target.matches("img[data-cwt-asset]")
        ) {
          var feature = event.target.closest(".cwt-feature-visual");
          var headBust = event.target.closest(".cwt-head-bust");
          if (headBust) {
            headBust.hidden = true;
          } else if (feature) {
            feature.hidden = true;
          } else {
            event.target.hidden = true;
          }
        }
      },
      true
    );
    root.innerHTML = [
      '<button id="cwt-avatar" class="cwt-avatar" type="button" aria-label="打开网页讲解助手">',
      avatarMarkup("cwt-launcher-avatar", "eager"),
      smokeMarkup(),
      "<span>网页讲解助手</span>",
      '<span id="cwt-unread" class="cwt-unread" hidden></span>',
      "</button>",
      '<section id="cwt-panel" class="cwt-panel" hidden aria-label="网页讲解助手">',
      '<div class="cwt-head">',
      bustMarkup("cwt-panel-bust", "eager"),
      '<div class="cwt-title">',
      "<div>网页讲解助手<small>页面讲解与资料问答</small></div>",
      "</div>",
      '<div class="cwt-head-actions">',
      '<button id="cwt-maximize" class="cwt-icon-btn cwt-maximize" type="button" aria-label="最大化窗口">' +
        maximizeIcon() +
        "</button>",
      '<button id="cwt-close" class="cwt-icon-btn" type="button" aria-label="关闭">×</button>',
      "</div>",
      "</div>",
      '<div class="cwt-chapter"><select id="cwt-chapter" class="cwt-select" aria-label="选择章节"><option value="">跟随当前页面</option></select></div>',
      '<div id="cwt-tour" class="cwt-tour" hidden>',
      '<div class="cwt-tour-head">',
      '<div class="cwt-tour-title">',
      '<small id="cwt-tour-step">主题参观</small>',
      '<strong id="cwt-tour-name">主题参观</strong>',
      "</div>",
      '<div class="cwt-tour-count"><strong id="cwt-tour-count">30 秒</strong><small><span id="cwt-tour-index">1</span>/<span id="cwt-tour-total">12</span></small></div>',
      "</div>",
      '<div class="cwt-tour-progress"><span id="cwt-tour-progress-bar"></span></div>',
      '<div id="cwt-tour-card"></div>',
      '<div class="cwt-tour-actions">',
      '<button id="cwt-tour-prev" class="cwt-tour-btn" type="button">上一站</button>',
      '<button id="cwt-tour-pause" class="cwt-tour-btn primary" type="button">暂停</button>',
      '<button id="cwt-tour-next" class="cwt-tour-btn" type="button">下一站</button>',
      '<button id="cwt-tour-return" class="cwt-tour-btn" type="button" hidden>回到参观</button>',
      '<button id="cwt-tour-exit" class="cwt-tour-btn danger" type="button">退出</button>',
      "</div>",
      "</div>",
      '<div id="cwt-messages" class="cwt-messages"></div>',
      '<div class="cwt-tools">',
      '<div>',
      '<button id="cwt-sequence" class="cwt-link" type="button">逐段讲解</button>',
      '<button id="cwt-pause" class="cwt-link" type="button" hidden>暂停</button>',
      "</div>",
      '<button id="cwt-stop" class="cwt-link" type="button" hidden>停止生成</button>',
      "</div>",
      '<form id="cwt-form" class="cwt-compose">',
      '<textarea id="cwt-input" class="cwt-input" rows="1" placeholder="问问当前页面或站内资料"></textarea>',
      '<button id="cwt-send" class="cwt-send" type="submit">发送</button>',
      "</form>",
      '<button id="cwt-resize" class="cwt-resize" type="button" aria-label="拖拽调整窗口大小"></button>',
      "</section>"
    ].join("");
    document.body.appendChild(root);

    document.getElementById("cwt-avatar").addEventListener("click", function () {
      if (!state.drag && !state.dragged) {
        setOpen(true);
      }
    });
    document.getElementById("cwt-close").addEventListener("click", function () {
      setOpen(false);
    });
    document.getElementById("cwt-chapter").addEventListener("change", function (event) {
      state.currentAnchor = event.target.value;
      if (state.currentAnchor) {
        highlight(state.currentAnchor);
      }
    });
    document.getElementById("cwt-sequence").addEventListener("click", function () {
      startSequentialExplain(state.sections);
    });
    document.getElementById("cwt-pause").addEventListener("click", function () {
      state.sequencePaused = !state.sequencePaused;
      this.textContent = state.sequencePaused ? "继续" : "暂停";
    });
    document.getElementById("cwt-stop").addEventListener("click", function () {
      if (state.abortController) {
        state.abortController.abort();
      }
    });
    document.getElementById("cwt-tour-prev").addEventListener("click", function () {
      goToTourStep(state.tour.index - 1);
    });
    document.getElementById("cwt-tour-next").addEventListener("click", function () {
      if (state.tour.index >= state.tour.route.stops.length - 1) {
        completeTour();
      } else {
        goToTourStep(state.tour.index + 1);
      }
    });
    document.getElementById("cwt-tour-pause").addEventListener("click", function () {
      if (state.tour.paused) {
        resumeTour();
      } else {
        pauseTour(false);
      }
    });
    document.getElementById("cwt-tour-return").addEventListener("click", function () {
      resumeTour();
    });
    document.getElementById("cwt-tour-exit").addEventListener("click", function () {
      stopTour();
    });
    document.getElementById("cwt-form").addEventListener("submit", function (event) {
      event.preventDefault();
      var input = document.getElementById("cwt-input");
      var question = input.value.trim();
      input.value = "";
      sendQuestion(question, "chat");
    });
    document.getElementById("cwt-input").addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        document.getElementById("cwt-form").requestSubmit();
      }
    });

    mountDrag();
    mountPanelResize();
    pageContext();
    updateChapterSelect();
    window.addEventListener("scroll", function () {
      if (trackTimer) {
        window.clearTimeout(trackTimer);
      }
      trackTimer = window.setTimeout(trackCurrentSection, 160);
    }, { passive: true });
    cachePage();
    var welcome = addMessage(
      "assistant",
      "你好，我是网页讲解助手。可以选择章节，也可以直接问当前页面或站内资料。"
    );
    addFeatureVisual(welcome, "bust.webp");
    var savedTour = sessionStorage.getItem(TOUR_STATE_KEY);
    if (savedTour) {
      setOpen(true);
      restoreTour();
    } else if (
      location.pathname === "/" &&
      !sessionStorage.getItem(TOUR_INVITE_KEY)
    ) {
      window.setTimeout(function () {
        if (!state.tour.active && !state.tour.inviteOpen) {
          showTourInvite("maozedong-railway-development");
        }
      }, 1200);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  window.GuideAgentWidget = {
    open: function () {
      setOpen(true);
    },
    close: function () {
      setOpen(false);
    },
    ask: function (question) {
      setOpen(true);
      return sendQuestion(question, "chat");
    },
    showTourInvite: function (routeId) {
      showTourInvite(routeId || "maozedong-railway-development");
    },
    startTour: function (routeId, mode) {
      setOpen(true);
      startTour(routeId || "maozedong-railway-development", mode || "page");
    },
    pauseTour: pauseTour,
    resumeTour: resumeTour,
    stopTour: stopTour,
    extractSections: extractSections,
    pageContext: pageContext
  };
})();

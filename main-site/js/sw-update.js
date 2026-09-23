// Service worker registration and the "new version" bar. The only place the
// site registers the worker: the bar needs the registration object, so no page
// should call navigator.serviceWorker.register() inline.
//
// A new worker never activates on its own. It installs and waits (sw.js has no
// skipWaiting in install), and only Reload on this bar promotes it.

(function () {
  const SW_URL = "/sw.js";

  const COPY = {
    label: "Update",
    ready: "A new version of QR Maker is ready.",
    reload: "Reload",
    later: "Not now",
  };

  let registration = null;
  let waitingWorker = null;
  let reloading = false;
  // This page view only. Never stored: "Not now" means not now.
  let dismissed = false;

  function render() {
    const existing = document.querySelector(".update-notice");

    if (!waitingWorker || dismissed) {
      if (existing) existing.remove();
      return;
    }

    const bar = existing || document.createElement("div");
    bar.className = "update-notice";
    // status, not alert: nothing is wrong.
    bar.setAttribute("role", "status");
    bar.setAttribute("aria-label", COPY.label);
    // COPY is literal strings, nothing here comes from the reader or a server.
    bar.innerHTML = `
      <div class="update-notice-inner">
        <p>${COPY.ready}</p>
        <button type="button" class="btn-primary" data-sw-update>${COPY.reload}</button>
        <button type="button" class="btn-ghost" data-sw-later>${COPY.later}</button>
      </div>
    `;

    bar.querySelector("[data-sw-update]").addEventListener("click", () => {
      // The only place anything asks for skipWaiting. The reload itself
      // happens on controllerchange, not here.
      if (waitingWorker) waitingWorker.postMessage("skip-waiting");
    });

    bar.querySelector("[data-sw-later]").addEventListener("click", () => {
      dismissed = true;
      render();
    });

    if (!existing) document.body.prepend(bar);
  }

  function watchForUpdate() {
    if (!registration) return;

    // Already waiting when the page opened: the usual case, on the first page
    // view after a deploy.
    if (registration.waiting && navigator.serviceWorker.controller) {
      waitingWorker = registration.waiting;
      render();
    }

    registration.addEventListener("updatefound", () => {
      const installing = registration.installing;
      if (!installing) return;

      installing.addEventListener("statechange", () => {
        // installed with no controller is a first install: there is no older
        // version on screen, so nothing to prompt about.
        if (installing.state === "installed" && navigator.serviceWorker.controller) {
          waitingWorker = registration.waiting || installing;
          render();
        }
      });
    });
  }

  function registerWorker() {
    if (!("serviceWorker" in navigator)) return;

    navigator.serviceWorker
      .register(SW_URL)
      .then((reg) => {
        registration = reg;
        watchForUpdate();
      })
      .catch((cause) => {
        // Private browsing in some browsers, and plain http origins other
        // than localhost, end up here. Not a reason to break the page.
        console.warn("service worker registration failed:", cause);
      });

    // Reload once the new worker has taken over, so the page comes back served
    // by it. Reloading straight from the click races the swap and brings the
    // old worker (and the bar) back. The flag stops a second controllerchange
    // from starting a reload loop.
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloading) return;
      reloading = true;
      window.location.reload();
    });
  }

  // After load, so precaching doesn't compete with the page's own first fetches.
  if (document.readyState === "complete") registerWorker();
  else window.addEventListener("load", registerWorker, { once: true });
})();

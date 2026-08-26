/* Progressive enhancement only — every control works without this file. */
(function () {
  "use strict";

  /* Auto-submit the statistics filter form when a select changes, so choosing
     a year does not also require finding the Apply button. The button stays in
     the markup for anyone without JavaScript. */
  var filters = document.querySelector("form[data-autosubmit]");
  if (filters) {
    var apply = filters.querySelector("[data-apply]");
    if (apply) apply.hidden = true;
    Array.prototype.forEach.call(filters.querySelectorAll("select"), function (select) {
      select.addEventListener("change", function () { filters.submit(); });
    });
  }

  /* Copy buttons for the generated handle.
     navigator.clipboard only exists in a secure context (HTTPS or localhost),
     so there is a selection-based fallback and, failing even that, the text is
     left selected for the visitor to copy manually. The button is created in
     the markup rather than injected, so it is present before this file runs. */
  Array.prototype.forEach.call(document.querySelectorAll("[data-copy-target]"), function (button) {
    var input = document.getElementById(button.getAttribute("data-copy-target"));
    if (!input) return;
    var original = button.textContent;
    var copiedLabel = button.getAttribute("data-copied-label") || "Copied";

    function flash(message) {
      button.textContent = message;
      button.setAttribute("aria-live", "polite");
      window.setTimeout(function () { button.textContent = original; }, 2000);
    }

    function selectAll() {
      input.focus();
      input.select();
      if (input.setSelectionRange) input.setSelectionRange(0, input.value.length);
    }

    button.addEventListener("click", function () {
      selectAll();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value).then(
          function () { flash(copiedLabel); },
          function () { flash("Press Ctrl+C"); }
        );
        return;
      }
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      flash(ok ? copiedLabel : "Press Ctrl+C");
    });
  });

  /* Guard against losing a half-filled year of readings to a stray click. */
  Array.prototype.forEach.call(document.querySelectorAll("form[data-dirty-guard]"), function (form) {
    var dirty = false;
    form.addEventListener("input", function () { dirty = true; });
    form.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (event) {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
  });
})();

// ADIF website behaviour. Plain JavaScript, no dependencies.
(function () {
  "use strict";

  // Copy buttons: <button data-copy="text">
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var text = button.getAttribute("data-copy");
    var done = function () {
      var old = button.textContent;
      button.textContent = "Copied";
      setTimeout(function () { button.textContent = old; }, 1400);
    };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done);
    else done();
  });

  // The formula banner: mint a fresh random ADID in the browser, to show that
  // the identifier is just 122 random bits with nothing about the product in it.
  function uuid4() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var b = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    var h = Array.prototype.map.call(b, function (x) { return (x + 256).toString(16).slice(1); }).join("");
    return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
  }
  function paint(target, id) {
    target.textContent = "";
    var parts = id.split("-");
    parts.forEach(function (part, i) {
      if (i === 2) {
        var v = document.createElement("span");
        v.className = "v4"; v.textContent = part.charAt(0);
        target.appendChild(v);
        target.appendChild(document.createTextNode(part.slice(1)));
      } else {
        target.appendChild(document.createTextNode(part));
      }
      if (i < parts.length - 1) target.appendChild(document.createTextNode("-"));
    });
  }
  var mint = document.querySelector("[data-mint]");
  if (mint) {
    var targets = document.querySelectorAll("[data-adid-text]");
    mint.addEventListener("click", function () {
      var id = uuid4();
      targets.forEach(function (t) {
        paint(t, id);
        t.classList.remove("minted"); void t.offsetWidth; t.classList.add("minted");
      });
      var count = document.querySelector("[data-mint-count]");
      if (count) count.textContent = String(Number(count.textContent || "0") + 1);
    });
  }

  // File input: show the chosen file name next to the button.
  document.querySelectorAll("input[type=file][data-show-name]").forEach(function (input) {
    input.addEventListener("change", function () {
      var out = document.getElementById(input.getAttribute("data-show-name"));
      if (out) out.textContent = input.files.length ? input.files[0].name : "";
    });
  });

  // Confirmations for actions that change a record's status.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
    });
  });
})();

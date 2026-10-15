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

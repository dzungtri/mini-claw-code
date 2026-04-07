(function () {
  var languages = {
    en: { label: "EN", title: "Switch to English" },
    zh: { label: "中文", title: "切换到中文" },
    vi: { label: "VI", title: "Chuyển sang tiếng Việt" },
  };
  var defined = /\/(en|zh|vi)\//;
  var match = window.location.pathname.match(defined);
  if (!match) return;

  var current = match[1];
  var buttons = document.querySelector(".right-buttons");
  if (buttons) {
    ["en", "zh", "vi"].reverse().forEach(function (language) {
      if (language === current) return;

      var link = document.createElement("a");
      link.href = window.location.pathname.replace(
        "/" + current + "/",
        "/" + language + "/"
      );
      link.className = "lang-toggle";
      link.title = languages[language].title;
      link.textContent = languages[language].label;

      buttons.insertBefore(link, buttons.firstChild);
    });
  }
})();

(function () {
    const savedTheme = localStorage.getItem("theme");

    if (savedTheme === "dark") {
        document.documentElement.setAttribute("data-theme", "dark");
    } else {
        document.documentElement.setAttribute("data-theme", "light");
    }

    window.toggleTheme = function () {
        const currentTheme =
            document.documentElement.getAttribute("data-theme");

        const newTheme = currentTheme === "dark" ? "light" : "dark";

        document.documentElement.setAttribute("data-theme", newTheme);
        localStorage.setItem("theme", newTheme);

        updateThemeIcon();
    };

    function updateThemeIcon() {
        const themeButton = document.querySelector("[data-theme-toggle]");

        if (!themeButton) return;

        const currentTheme =
            document.documentElement.getAttribute("data-theme");

        if (currentTheme === "dark") {
            themeButton.innerHTML = "☀";
            themeButton.setAttribute("aria-label", "Switch to Light Mode");
            themeButton.setAttribute("title", "Switch to Light Mode");
        } else {
            themeButton.innerHTML = "☾";
            themeButton.setAttribute("aria-label", "Switch to Dark Mode");
            themeButton.setAttribute("title", "Switch to Dark Mode");
        }
    }

    document.addEventListener("DOMContentLoaded", updateThemeIcon);
})();

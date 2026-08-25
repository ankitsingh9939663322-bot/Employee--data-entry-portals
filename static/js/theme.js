(function () {
    "use strict";

    const STORAGE_KEY = "theme";
    const root = document.documentElement;

    /* =========================================================
       1. INITIAL THEME
       ========================================================= */

    const savedTheme = localStorage.getItem(STORAGE_KEY);

    if (savedTheme === "dark") {
        root.setAttribute("data-theme", "dark");
    } else {
        root.setAttribute("data-theme", "light");
    }


    /* =========================================================
       2. PROFESSIONAL SVG ICONS
       ========================================================= */

    const moonIcon = `
        <svg
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
        >
            <path
                d="M21 12.8A8.5 8.5 0 0 1 11.2 3
                   a8.5 8.5 0 1 0 9.8 9.8Z"
            ></path>
        </svg>
    `;

    const sunIcon = `
        <svg
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
        >
            <circle
                cx="12"
                cy="12"
                r="4"
            ></circle>

            <path
                d="M12 2v2
                   M12 20v2
                   M2 12h2
                   M20 12h2
                   M4.93 4.93l1.41 1.41
                   M17.66 17.66l1.41 1.41
                   M4.93 19.07l1.41-1.41
                   M17.66 6.34l1.41-1.41"
            ></path>
        </svg>
    `;


    /* =========================================================
       3. CREATE THEME BUTTON AUTOMATICALLY
       ========================================================= */

    function createThemeButton() {

        /*
         * If button already exists, don't create another one.
         */
        let themeButton =
            document.querySelector("[data-theme-toggle]");

        if (themeButton) {
            return themeButton;
        }


        /*
         * Find existing Nexora header.
         */
        const header =
            document.querySelector(".brand");

        if (!header) {
            return null;
        }


        /*
         * Create button.
         */
        themeButton =
            document.createElement("button");

        themeButton.type = "button";

        themeButton.className =
            "theme-toggle";

        themeButton.setAttribute(
            "data-theme-toggle",
            ""
        );

        themeButton.setAttribute(
            "aria-label",
            "Switch to Dark Mode"
        );

        themeButton.setAttribute(
            "title",
            "Switch to Dark Mode"
        );


        /*
         * Place button inside header.
         */
        header.appendChild(themeButton);


        /*
         * Toggle theme when clicked.
         */
        themeButton.addEventListener(
            "click",
            window.toggleTheme
        );


        return themeButton;
    }


    /* =========================================================
       4. UPDATE ICON
       ========================================================= */

    function updateThemeIcon() {

        const themeButton =
            document.querySelector(
                "[data-theme-toggle]"
            );

        if (!themeButton) {
            return;
        }

        const currentTheme =
            root.getAttribute("data-theme");


        if (currentTheme === "dark") {

            /*
             * Dark mode active
             * Show sun → click for light mode
             */

            themeButton.innerHTML = sunIcon;

            themeButton.setAttribute(
                "aria-label",
                "Switch to Light Mode"
            );

            themeButton.setAttribute(
                "title",
                "Switch to Light Mode"
            );

            themeButton.setAttribute(
                "aria-pressed",
                "true"
            );

        } else {

            /*
             * Light mode active
             * Show moon → click for dark mode
             */

            themeButton.innerHTML = moonIcon;

            themeButton.setAttribute(
                "aria-label",
                "Switch to Dark Mode"
            );

            themeButton.setAttribute(
                "title",
                "Switch to Dark Mode"
            );

            themeButton.setAttribute(
                "aria-pressed",
                "false"
            );
        }
    }


    /* =========================================================
       5. TOGGLE THEME
       ========================================================= */

    window.toggleTheme = function () {

        const currentTheme =
            root.getAttribute("data-theme");

        const newTheme =
            currentTheme === "dark"
                ? "light"
                : "dark";


        root.setAttribute(
            "data-theme",
            newTheme
        );

        localStorage.setItem(
            STORAGE_KEY,
            newTheme
        );

        updateThemeIcon();
    };


    /* =========================================================
       6. INITIALIZE
       ========================================================= */

    function initializeTheme() {

        createThemeButton();

        updateThemeIcon();
    }


    if (
        document.readyState ===
        "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            initializeTheme,
            { once: true }
        );

    } else {

        initializeTheme();
    }

})();

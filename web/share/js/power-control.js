(() => {
    if (window.__pikvmPowerMenuLoaded) return;
    window.__pikvmPowerMenuLoaded = true;

    // ========================================================
    // STYLE
    // ========================================================

    const style = document.createElement("style");

    style.textContent = `
        #pkpm-root {
            position: fixed;
            right: 14px;
            bottom: 48px;
            z-index: 2147483000;
            font-family: Arial, Helvetica, sans-serif;
            font-size: 14px;
        }

        #pkpm-toggle {
            height: 36px;
            min-width: 104px;

            padding: 0 12px;

            display: flex;
            align-items: center;
            justify-content: center;
            gap: 7px;

            background: #383d45;
            color: #B2B2B2;

            border: 1px solid #171a1f;
            border-top-color: #626871;
            border-radius: 3px;

            box-shadow: 0 2px 5px rgba(0,0,0,.40);

            cursor: pointer;

            font: inherit;
            font-weight: bold;
        }

        #pkpm-toggle:hover,
        #pkpm-toggle.open {
            background: #454b54;
            color: #dedede;
        }

        #pkpm-menu {
            position: absolute;

            right: 0;
            bottom: 42px;

            width: 205px;

            display: none;

            background: #30343b;

            border: 1px solid #171a1f;
            border-top: 2px solid #5f9fcf;

            box-shadow: 0 4px 12px rgba(0,0,0,.55);
        }

        #pkpm-menu.open {
            display: block;
        }

        .pkpm-title {
            padding: 8px 10px;

            background: #252a31;

            border-bottom: 1px solid #181c21;

            color: #d5d5d5;

            font-weight: bold;
        }

        .pkpm-item {
            width: 100%;
            height: 39px;

            padding: 0 10px;

            display: flex;
            align-items: center;
            gap: 9px;

            background: #383d45;
            color: #d0d0d0;

            border: 0;
            border-bottom: 1px solid #20242a;

            cursor: pointer;

            font: inherit;
            font-weight: bold;

            text-align: left;
        }

        .pkpm-item:last-child {
            border-bottom: 0;
        }

        .pkpm-item:hover {
            background: #484e57;
            color: #ffffff;
        }

        .pkpm-item.poweroff:hover {
            background: #563737;
        }

        .pkpm-icon {
            width: 20px;

            color: #B2B2B2;

            text-align: center;
            font-size: 17px;
        }

        .pkpm-item:disabled,
        #pkpm-toggle:disabled {
            opacity: .45;
            cursor: default;
        }

        #pkpm-status {
            display: none;

            padding: 9px 10px;

            background: #20242a;
            color: #cfcfcf;

            border-top: 1px solid #171a1f;

            font-size: 12px;
            text-align: center;
        }

        #pkpm-status.show {
            display: block;
        }
    `;

    document.head.appendChild(style);


    // ========================================================
    // INTERFACE
    // ========================================================

    const root = document.createElement("div");
    root.id = "pkpm-root";

    root.innerHTML = `
        <div id="pkpm-menu">

            <div class="pkpm-title">
                Power Control
            </div>

            <button
                id="pkpm-restart"
                class="pkpm-item"
                type="button"
            >
                <span class="pkpm-icon">↻</span>
                <span>Redémarrer PiKVM</span>
            </button>

            <button
                id="pkpm-poweroff"
                class="pkpm-item poweroff"
                type="button"
            >
                <span class="pkpm-icon">⏻</span>
                <span>Éteindre PiKVM</span>
            </button>

            <div id="pkpm-status"></div>

        </div>

        <button
            id="pkpm-toggle"
            type="button"
            title="Power Control"
        >
            <span>⏻</span>
            <span>Power</span>
        </button>
    `;

    document.body.appendChild(root);


    const toggle =
        document.getElementById("pkpm-toggle");

    const menu =
        document.getElementById("pkpm-menu");

    const restart =
        document.getElementById("pkpm-restart");

    const poweroff =
        document.getElementById("pkpm-poweroff");

    const status =
        document.getElementById("pkpm-status");


    // ========================================================
    // MENU
    // ========================================================

    function closeMenu() {
        menu.classList.remove("open");
        toggle.classList.remove("open");
    }

    toggle.addEventListener("click", event => {
        event.stopPropagation();

        menu.classList.toggle("open");
        toggle.classList.toggle(
            "open",
            menu.classList.contains("open")
        );
    });

    document.addEventListener("click", event => {
        if (!root.contains(event.target)) {
            closeMenu();
        }
    });


    // ========================================================
    // API
    // ========================================================

    async function api(action) {

        const response = await fetch(
            "/extras/wifi-wizard/api/" + action,
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                credentials: "same-origin",

                cache: "no-store",

                body: "{}"
            }
        );

        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error(
                data.error || "Erreur API"
            );
        }

        return data;
    }


    function setBusy(text) {

        restart.disabled = true;
        poweroff.disabled = true;
        toggle.disabled = true;

        status.textContent = text;
        status.classList.add("show");
    }


    function resetBusy() {

        restart.disabled = false;
        poweroff.disabled = false;
        toggle.disabled = false;

        status.classList.remove("show");
    }


    // ========================================================
    // REDÉMARRAGE
    // ========================================================

    restart.addEventListener("click", async () => {

        if (!confirm(
            "Redémarrer PiKVM ?"
        )) {
            return;
        }

        setBusy(
            "Redémarrage en cours..."
        );

        try {

            await api(
                "pikvm-restart"
            );

            setTimeout(() => {
                location.reload();
            }, 4500);

        } catch (error) {

            alert(
                "Erreur : " +
                error.message
            );

            resetBusy();
        }
    });


    // ========================================================
    // EXTINCTION
    // ========================================================

    poweroff.addEventListener("click", async () => {

        if (!confirm(
            "Éteindre complètement le PiKVM ?"
        )) {
            return;
        }

        setBusy(
            "Extinction en cours..."
        );

        try {

            await api(
                "pikvm-poweroff"
            );

        } catch (error) {

            alert(
                "Erreur : " +
                error.message
            );

            resetBusy();
        }
    });

})();


// ============================================================
// PIKVM-BATTERY-INDICATOR
// ============================================================

(() => {

    const root = document.getElementById("pkpm-root");

    if (!root) return;


    // --------------------------------------------------------
    // STYLE
    // --------------------------------------------------------

    const style = document.createElement("style");

    style.textContent = `
        #pkpm-root {
            display: flex;
            align-items: flex-end;
            gap: 6px;
        }

        #pk-battery {
            height: 36px;
            min-width: 91px;

            padding: 0 9px;

            display: flex;
            align-items: center;
            justify-content: center;
            gap: 7px;

            background: #383d45;
            color: #B2B2B2;

            border: 1px solid #171a1f;
            border-top-color: #626871;
            border-radius: 3px;

            box-shadow: 0 2px 5px rgba(0,0,0,.40);

            font-family: Arial, Helvetica, sans-serif;
            font-size: 13px;
            font-weight: bold;
        }

        #pk-battery-case {
            position: relative;

            width: 25px;
            height: 12px;

            border: 2px solid #B2B2B2;
            border-radius: 2px;
        }

        #pk-battery-case::after {
            content: "";

            position: absolute;

            right: -5px;
            top: 3px;

            width: 3px;
            height: 6px;

            background: #B2B2B2;
            border-radius: 0 1px 1px 0;
        }

        #pk-battery-fill {
            position: absolute;

            left: 2px;
            top: 2px;
            bottom: 2px;

            width: 0%;

            background: #B2B2B2;

            transition: width .3s;
        }

        #pk-battery-text {
            min-width: 30px;
            text-align: right;
        }
    `;

    document.head.appendChild(style);


    // --------------------------------------------------------
    // INDICATEUR
    // --------------------------------------------------------

    const battery = document.createElement("div");

    battery.id = "pk-battery";

    battery.innerHTML = `
        <div id="pk-battery-case">
            <div id="pk-battery-fill"></div>
        </div>

        <span id="pk-battery-text">--%</span>
    `;


    const powerButton =
        document.getElementById("pkpm-toggle");

    root.insertBefore(
        battery,
        powerButton
    );


    const fill =
        document.getElementById(
            "pk-battery-fill"
        );

    const text =
        document.getElementById(
            "pk-battery-text"
        );


    // --------------------------------------------------------
    // LECTURE
    // --------------------------------------------------------

    async function updateBattery() {

        try {

            const response = await fetch(
                "/extras/wifi-wizard/api/battery",
                {
                    cache: "no-store",
                    credentials: "same-origin"
                }
            );

            const data =
                await response.json();

            if (!data.ok) {
                throw new Error();
            }

            const percent =
                Math.max(
                    0,
                    Math.min(
                        100,
                        Number(
                            data.battery.percent
                        )
                    )
                );

            const voltage =
                Number(
                    data.battery.voltage
                );

            const charging =
                Boolean(
                    data.battery.charging
                );

            const chargeRate =
                Number(
                    data.battery.charge_rate
                );


            const innerWidth = 21;

            fill.style.width =
                `${Math.round(innerWidth * percent / 100)}px`;

            text.textContent =
                charging
                    ? `⚡ ${Math.round(percent)}%`
                    : `${Math.round(percent)}%`;

            battery.title =
                (charging
                    ? `En charge\n`
                    : `Batterie\n`) +
                `Niveau : ${percent.toFixed(1)} %\n` +
                `Tension : ${voltage.toFixed(3)} V\n` +
                `Variation : ${chargeRate >= 0 ? "+" : ""}${chargeRate.toFixed(2)} %/h`;

        }

        catch (_) {

            fill.style.width = "0%";
            text.textContent = "--%";

            battery.title =
                "Batterie indisponible";
        }
    }


    updateBattery();

    setInterval(
        updateBattery,
        10000
    );

})();


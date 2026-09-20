(() => {
    "use strict";

    if (window.__pikvmUsbTransferLoaded) {
        return;
    }

    window.__pikvmUsbTransferLoaded = true;

    let busy = false;
    let lastState = null;

    // Une fois l'import terminé, le message reste visible
    // jusqu'à la première fermeture du menu Drive.
    let doneDismissed = false;
    let driveWasVisible = false;


    // ========================================================
    // HTTP
    // ========================================================

    async function request(url, options = {}) {

        const response = await fetch(
            url,
            {
                credentials: "same-origin",
                cache: "no-store",
                ...options
            }
        );

        let data = {};

        try {
            data = await response.json();
        }
        catch (_) {
            // Réponse non JSON.
        }

        if (!response.ok || data.ok === false) {

            throw new Error(
                data.error
                || data.message
                || `Erreur HTTP ${response.status}`
            );
        }

        return data;
    }


    function transferGet() {

        return request(
            "/extras/wifi-wizard/api/usb-transfer/status"
        );
    }


    function transferPost(action) {

        return request(
            "/extras/wifi-wizard/api/usb-transfer/" + action,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: "{}"
            }
        );
    }


    async function getNativeMsd() {

        const data = await request(
            "/api/msd"
        );

        return data.result;
    }


    async function nativePost(path, params) {

        const query =
            new URLSearchParams(params);

        return request(
            path + "?" + query.toString(),
            {
                method: "POST"
            }
        );
    }


    async function syncNormalDrive() {

        await nativePost(
            "/api/msd/set_params",
            {
                image: "",
                cdrom: 1,
                rw: 0
            }
        );
    }


    // ========================================================
    // INTERFACE
    // ========================================================

    function init() {

        const menu =
            document.getElementById(
                "msd-menu"
            );

        if (!menu) {

            setTimeout(
                init,
                500
            );

            return;
        }


        if (
            document.getElementById(
                "pk-usb-transfer-row"
            )
        ) {
            return;
        }


        const buttons =
            menu.querySelector(
                ".buttons.buttons-row"
            );

        if (!buttons) {

            setTimeout(
                init,
                500
            );

            return;
        }


        const row =
            document.createElement("div");

        row.id =
            "pk-usb-transfer-row";

        row.className =
            "buttons buttons-row";

        row.innerHTML = `
            <button
                id="pk-usb-transfer-start"
                class="row50"
                type="button"
            >
                Transfert USB
            </button>

            <button
                id="pk-usb-transfer-finish"
                class="row50"
                type="button"
                disabled
            >
                Terminer transfert
            </button>
        `;


        const status =
            document.createElement("div");

        status.id =
            "pk-usb-transfer-status";

        status.className =
            "text";

        status.style.display =
            "none";

        status.style.padding =
            "8px 4px 4px";

        status.style.fontSize =
            "12px";

        status.style.textAlign =
            "center";


        buttons.insertAdjacentElement(
            "afterend",
            row
        );

        row.insertAdjacentElement(
            "afterend",
            status
        );


        document
            .getElementById(
                "pk-usb-transfer-start"
            )
            .addEventListener(
                "click",
                startTransfer
            );


        document
            .getElementById(
                "pk-usb-transfer-finish"
            )
            .addEventListener(
                "click",
                finishTransfer
            );


        refresh();

        setInterval(
            refresh,
            1500
        );
    }


    function elements() {

        return {
            start:
                document.getElementById(
                    "pk-usb-transfer-start"
                ),

            finish:
                document.getElementById(
                    "pk-usb-transfer-finish"
                ),

            status:
                document.getElementById(
                    "pk-usb-transfer-status"
                )
        };
    }


    function showStatus(text, error = false) {

        const {status} =
            elements();

        if (!status) {
            return;
        }

        status.textContent =
            text || "";

        status.style.display =
            text
            ? "block"
            : "none";

        status.style.color =
            error
            ? "#ff7777"
            : "";
    }


    function lockNativeDrive() {

        const ids = [
            "msd-image-selector",
            "msd-remove-button",
            "msd-download-button",
            "msd-rw-switch",
            "msd-connect-button",
            "msd-disconnect-button",
            "msd-select-new-button",
            "msd-reset-button"
        ];

        for (const id of ids) {

            const el =
                document.getElementById(id);

            if (el) {
                el.disabled = true;
            }
        }


        for (
            const el
            of document.querySelectorAll(
                'input[name="msd-mode-radio"]'
            )
        ) {
            el.disabled = true;
        }
    }


    // ========================================================
    // DEMARRAGE
    // ========================================================

    async function startTransfer() {

        if (busy) {
            return;
        }


        try {

            busy = true;

            showStatus(
                "Préparation du transfert USB..."
            );


            const msd =
                await getNativeMsd();


            if (
                msd.drive
                && msd.drive.connected
            ) {

                const name =
                    msd.drive.image?.name
                    || "le lecteur actuel";


                if (
                    !confirm(
                        `${name} est actuellement connecté.\n\n`
                        + "Il doit être déconnecté pour "
                        + "activer PIKVM-XFER.\n\n"
                        + "Continuer ?"
                    )
                ) {
                    return;
                }


                await nativePost(
                    "/api/msd/set_connected",
                    {
                        connected: 0
                    }
                );
            }


            const data =
                await transferPost(
                    "start"
                );


            showStatus(
                data.transfer?.message
                || "PIKVM-XFER connecté au PC"
            );

        }
        catch (error) {

            showStatus(
                "Erreur : " + error.message,
                true
            );

        }
        finally {

            busy = false;

            setTimeout(
                refresh,
                300
            );
        }
    }


    // ========================================================
    // IMPORT
    // ========================================================

    async function finishTransfer() {

        if (busy) {
            return;
        }


        if (
            !confirm(
                "Avant de continuer, éjecte PIKVM-XFER "
                + "depuis Windows.\n\n"
                + "Lancer maintenant l'import des images ?"
            )
        ) {
            return;
        }


        try {

            busy = true;

            showStatus(
                "Démarrage de l'import..."
            );


            await transferPost(
                "import"
            );

        }
        catch (error) {

            showStatus(
                "Erreur : " + error.message,
                true
            );

        }
        finally {

            busy = false;

            setTimeout(
                refresh,
                300
            );
        }
    }


    // ========================================================
    // ETAT
    // ========================================================

    function driveMenuVisible() {

        const menu =
            document.getElementById(
                "msd-menu"
            );

        if (!menu) {
            return false;
        }

        const style =
            window.getComputedStyle(menu);

        return (
            style.display !== "none"
            && style.visibility !== "hidden"
            && menu.getClientRects().length > 0
        );
    }


    async function refresh() {

        const {
            start,
            finish
        } = elements();


        if (!start || !finish) {
            return;
        }


        try {

            const data =
                await transferGet();

            const transfer =
                data.transfer || {};

            const state =
                transfer.state || "idle";

            const drive =
                transfer.drive || {};

            const menuVisible =
                driveMenuVisible();

            if (
                lastState === "done"
                && driveWasVisible
                && !menuVisible
            ) {
                doneDismissed = true;
            }

            if (state !== "done") {
                doneDismissed = false;
            }

            driveWasVisible =
                menuVisible;

            const active =
                Boolean(
                    drive.transfer_active
                );


            const operating = [
                "starting",
                "stopping",
                "importing",
                "preparing"
            ].includes(state);


            start.disabled =
                busy
                || operating
                || active;


            finish.disabled =
                busy
                || operating
                || !active;


            if (active || operating) {
                lockNativeDrive();
            }


            if (active) {

                showStatus(
                    "PIKVM-XFER connecté — "
                    + "copiez vos ISO/IMG puis "
                    + "éjectez le lecteur dans Windows."
                );

            }
            else if (state === "starting") {

                showStatus(
                    transfer.message
                    || "Activation du transfert..."
                );

            }
            else if (state === "stopping") {

                showStatus(
                    transfer.message
                    || "Déconnexion USB..."
                );

            }
            else if (state === "importing") {

                let text =
                    transfer.message
                    || "Import en cours...";


                if (
                    transfer.percent !== undefined
                    && transfer.percent !== null
                ) {
                    text += (
                        ` — ${Math.round(transfer.percent)}%`
                    );
                }

                if (transfer.total) {
                    text += (
                        ` (${transfer.done || 0}`
                        + `/${transfer.total})`
                    );
                }


                showStatus(text);

            }
            else if (state === "preparing") {

                showStatus(
                    transfer.message
                    || "Nettoyage du disque USB..."
                );

            }
            else if (state === "error") {

                showStatus(
                    transfer.message
                    || "Erreur transfert USB",
                    true
                );

            }
            else if (state === "done") {

                if (lastState !== "done") {

                    try {
                        await syncNormalDrive();
                    }
                    catch (_) {
                        // Le Drive physique est déjà normal.
                    }
                }


                const imported =
                    transfer.imported || [];


                if (doneDismissed) {

                    showStatus("");

                }
                else {

                    showStatus(
                        imported.length
                        ? (
                            "Import terminé : "
                            + imported.join(", ")
                        )
                        : "Import terminé"
                    );
                }

            }
            else {

                showStatus("");
            }


            lastState = state;

        }
        catch (error) {

            showStatus(
                "USB : " + error.message,
                true
            );
        }
    }


    // ========================================================
    // CHARGEMENT
    // ========================================================

    if (
        document.readyState
        === "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            init
        );

    }
    else {

        init();
    }

})();

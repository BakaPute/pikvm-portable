(() => {
    "use strict";

    if (window.__pikvmUsbTransferLoaded) {
        return;
    }

    window.__pikvmUsbTransferLoaded = true;

    let busy = false;
    let polling = false;
    let lastState = null;

    // Une fois l'import terminé, le message reste visible
    // jusqu'à la première fermeture du menu Drive.
    let doneDismissed = false;
    let driveWasVisible = false;


    // ========================================================
    // HTTP
    // ========================================================

    async function request(url, options = {}) {

        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), options.method === 'POST' ? 250000 : 10000);
        let response;
        try {
            response = await fetch(url, {credentials: 'same-origin', cache: 'no-store',
                ...options, signal: controller.signal});
        } catch (error) {
            if (controller.signal.aborted) throw new Error('Délai USB dépassé ; vérifier l’état avant de réessayer.');
            throw error;
        } finally { clearTimeout(timer); }

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
                    "Content-Type": "application/json", "X-Pikvm-Share": "1"
                },
                body: JSON.stringify(action === "start" ? {allow_usb_reset: true} : {})
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
            <button id="pk-usb-transfer-import" type="button" disabled>Importer / reprendre les ISO</button>
        `;

        row.querySelector('#pk-usb-transfer-import').addEventListener('click', importImages);

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

                throw new Error("Éjecte proprement le Drive 0 côté PC avant le transfert.");
            }


            if (!confirm("L’activation interrompt temporairement tout l’USB, clavier et souris inclus. Drive 1 et SHARE doivent être libérés. Continuer ?")) return;

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
        if (busy) return;
        busy = true;
        try {
            const data = await transferPost('stop');
            showStatus(data.transfer?.message || 'Transfert terminé ; source conservée.');
        } catch (error) { showStatus(error.message, true); }
        finally { busy = false; await refresh(); }
    }

    async function importImages() {

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
        if (polling) return;

        const {
            start,
            finish
        } = elements();


        if (!start || !finish) {
            return;
        }


        polling = true;
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


            const unknown = !drive.known || state === 'unknown';
            const operating = [
                "starting",
                "stopping",
                "importing",
                "preparing"
            ].includes(state);


            start.disabled =
                busy
                || operating
                || active || unknown || Boolean(drive.image);


            finish.disabled =
                busy
                || operating
                || unknown || Boolean(drive.image) || !transfer.exists;
            document.getElementById('pk-usb-transfer-import').disabled = finish.disabled;


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
            else if (["error", "unknown", "interrupted"].includes(state)) {

                showStatus(
                    transfer.message
                    || "Erreur transfert USB",
                    true
                );

            }
            else if (state === "done") {

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

                showStatus(transfer.message || "");
            }


            lastState = state;

        }
        catch (error) {
            start.disabled = finish.disabled = true;
            document.getElementById('pk-usb-transfer-import').disabled = true;

            showStatus(
                "USB : " + error.message,
                true
            );
        }
        finally { polling = false; }
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

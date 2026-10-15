/* PiKVM Portable — Navigateur de dossiers dans Drive.
   Ne remplace pas le plugin MSD, n'agit pas sur ConfigFS/UDC. */
(() => {
    "use strict";

    if (window.__pkDriveFoldersV1) return;
    window.__pkDriveFoldersV1 = true;

    const selector = document.getElementById("msd-image-selector");
    const menu = document.getElementById("msd-menu");
    if (!selector || !menu) return;

    const filter = document.getElementById("msd-filter-input");
    const filterRow = filter?.closest("tr") || null;
    const originalFilterDisplay = filterRow?.style.display || "";

    const css = document.createElement("style");
    css.textContent = `
        #pkdf-launch {
            width: 100%; min-height: 33px; padding: 6px 9px;
            background: #363c45; color: #e2e2e2;
            border: 1px solid #58616e; border-radius: 2px;
            text-align: left; cursor: pointer; font: inherit;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        #pkdf-launch:hover { background: #444b56; }
        #pkdf-panel {
            margin-top: 6px; width: 100%; max-height: 365px;
            overflow-y: auto; overflow-x: hidden;
            background: #252a31; border: 1px solid #59616b;
            color: #dedede; font-family: Arial, sans-serif; font-size: 13px;
        }
        #pkdf-panel[hidden] { display: none !important; }
        #pkdf-crumbs {
            display: flex; flex-wrap: wrap; align-items: center;
            gap: 2px; padding: 7px; background: #1d2229;
            border-bottom: 1px solid #3a424c;
        }
        #pkdf-panel button { cursor: pointer; font: inherit; }
        #pkdf-crumbs button {
            border: 0; background: transparent; padding: 3px 4px;
            color: #94cafa;
        }
        #pkdf-crumbs button:hover { text-decoration: underline; }
        #pkdf-search {
            box-sizing: border-box; display: block;
            width: calc(100% - 14px); margin: 7px;
            background: #151a20; color: #fff;
            border: 1px solid #56606e; padding: 7px;
            font: inherit;
        }
        #pkdf-hint {
            padding: 4px 9px 8px; color: #aeb6c0; font-size: 12px;
        }
        #pkdf-items { max-height: 236px; overflow-y: auto; }
        #pkdf-items button {
            width: 100%; min-height: 37px; display: flex;
            align-items: center; gap: 8px; padding: 7px 9px;
            color: #e3e3e3; background: #303640; border: 0;
            border-bottom: 1px solid #20262d; text-align: left;
        }
        #pkdf-items button:hover:not(:disabled) { background: #414956; }
        #pkdf-items button:disabled { opacity: .5; cursor: not-allowed; }
        .pkdf-icon { flex: 0 0 20px; font-size: 17px; }
        .pkdf-name { min-width: 0; flex: 1; overflow-wrap: anywhere; }
        .pkdf-meta { flex: 0 0 auto; color: #acb4be; font-size: 11px; }
        #pkdf-items .pkdf-current { border-left: 3px solid #5f9fcf; }
        #pkdf-items .pkdf-empty {
            padding: 14px 9px; color: #abb3bc; text-align: center;
        }
    `;
    document.head.append(css);

    const browser = document.createElement("div");
    browser.id = "pkdf-browser";
    browser.innerHTML = `
        <button id="pkdf-launch" type="button" title="Parcourir les images par dossier">📁 Choisir une image… ▾</button>
        <div id="pkdf-panel" hidden>
            <div id="pkdf-crumbs"></div>
            <input id="pkdf-search" type="search" autocomplete="off" placeholder="Rechercher une ISO dans tous les dossiers…">
            <div id="pkdf-hint"></div>
            <div id="pkdf-items"></div>
        </div>
    `;
    selector.before(browser);

    const launch = browser.querySelector("#pkdf-launch");
    const panel = browser.querySelector("#pkdf-panel");
    const crumbs = browser.querySelector("#pkdf-crumbs");
    const search = browser.querySelector("#pkdf-search");
    const hint = browser.querySelector("#pkdf-hint");
    const items = browser.querySelector("#pkdf-items");

    let state = null;
    let folder = "";
    let inFlight = false;

    // Le select officiel reste dans le DOM pour les boutons natifs
    // (téléchargement/suppression) et les mises à jour WebSocket.
    const showNative = () => {
        selector.style.display = "";
        if (filterRow) filterRow.style.display = originalFilterDisplay;
        browser.hidden = true;
    };

    async function api(path, options = {}) {
        const response = await fetch(path, {
            cache: "no-store", credentials: "same-origin", ...options,
        });
        let data = {};
        try { data = await response.json(); } catch (_) { /* Réponse invalide */ }
        if (!response.ok || data.ok === false) {
            throw new Error(data.result?.error_msg || data.error_msg || data.error || `HTTP ${response.status}`);
        }
        return data.result || data;
    }

    const allImages = () => Object.entries(state?.storage?.images || {})
        .filter(([name]) => name && !name.split("/").some(part => part.startsWith(".")));

    function size(bytes) {
        const n = Number(bytes || 0);
        if (n >= 1073741824) return `${(n / 1073741824).toFixed(2)} Gio`;
        return `${(n / 1048576).toFixed(1)} Mio`;
    }

    function currentName() {
        return state?.drive?.image?.name || "";
    }

    function busy() {
        return Boolean(!state?.online || state.busy || state.drive?.connected
            || state.storage?.uploading || state.storage?.downloading || inFlight);
    }

    function makeButton(label, action, className = "") {
        const el = document.createElement("button");
        el.type = "button";
        el.textContent = label;
        if (className) el.className = className;
        el.addEventListener("click", action);
        return el;
    }

    function goTo(path) {
        folder = path;
        search.value = "";
        draw();
    }

    function draw() {
        if (!state) return;
        const selected = currentName();
        const selectedInfo = selected ? `💿 ${selected.split("/").pop()}` : "📁 Choisir une image… ▾";
        launch.textContent = selectedInfo;
        launch.title = selected || "Parcourir les images par dossier";

        if (panel.hidden) return;
        crumbs.replaceChildren();
        const segments = folder ? folder.split("/") : [];
        crumbs.append(makeButton("Stockage", () => goTo("")));
        let path = "";
        for (const segment of segments) {
            path += (path ? "/" : "") + segment;
            const p = path;
            crumbs.append(document.createTextNode(" / "));
            crumbs.append(makeButton(segment, () => goTo(p)));
        }

        items.replaceChildren();
        const images = allImages();
        const q = search.value.trim().toLocaleLowerCase("fr");
        const seenDirs = new Map();
        const files = [];
        for (const [name, info] of images) {
            if (q) {
                if (name.toLocaleLowerCase("fr").includes(q)) files.push([name, info]);
                continue;
            }
            if (folder && !name.startsWith(folder + "/")) continue;
            const rest = folder ? name.slice(folder.length + 1) : name;
            const slash = rest.indexOf("/");
            if (slash === -1) files.push([name, info]);
            else {
                const next = rest.slice(0, slash);
                seenDirs.set(next, (seenDirs.get(next) || 0) + 1);
            }
        }

        const entry = (icon, title, meta, onClick, disabled = false, current = false) => {
            const row = makeButton("", onClick, current ? "pkdf-current" : "");
            row.disabled = disabled;
            const i = document.createElement("span");
            i.className = "pkdf-icon";
            i.textContent = icon;
            const n = document.createElement("span");
            n.className = "pkdf-name";
            n.textContent = title;
            const m = document.createElement("span");
            m.className = "pkdf-meta";
            m.textContent = meta;
            row.append(i, n, m);
            items.append(row);
        };

        if (!q && folder) {
            entry("↩", ".. Dossier parent", "", () => goTo(folder.split("/").slice(0, -1).join("/")));
        }
        [...seenDirs.entries()].sort((a, b) => a[0].localeCompare(b[0], "fr"))
            .forEach(([name, count]) => {
                const next = folder ? `${folder}/${name}` : name;
                entry("📁", name, `${count} image(s) ›`, () => goTo(next));
            });
        files.sort((a, b) => a[0].localeCompare(b[0], "fr"));
        files.forEach(([name, info]) => {
            const title = q ? name : name.split("/").pop();
            entry("💿", title,
                info.complete ? size(info.size) : "Incomplète",
                () => selectImage(name), busy() || !info.complete,
                selected === name);
        });

        if (!q || q.length) {
            entry("⊘", "Ne sélectionner aucune image", "", () => selectImage(""), busy(), !selected);
        }
        if (items.children.length === 0) {
            const empty = document.createElement("div");
            empty.className = "pkdf-empty";
            empty.textContent = "Aucune image dans ce dossier";
            items.append(empty);
        }
        hint.textContent = busy()
            ? (state.drive?.connected ? "Drive connecté : déconnecter avant de changer d'image." : "Drive occupé : sélection indisponible pour le moment.")
            : `${images.length} image(s) · ${seenDirs.size} sous-dossier(s) dans cette vue`;
    }

    async function refresh() {
        try {
            state = await api("/api/msd");
            draw();
        } catch (error) {
            hint.textContent = `Erreur : ${error.message}`;
            // En cas d'échec initial, on conserve le sélecteur officiel.
            if (!state) showNative();
        }
    }

    async function selectImage(name) {
        if (inFlight) return;
        inFlight = true;
        try {
            state = await api("/api/msd");
            if (!state.online || state.busy || state.drive?.connected || state.storage?.uploading || state.storage?.downloading) {
                throw new Error("Drive occupé ou connecté : réessaie après la fin de l'opération.");
            }
            if (name && !state.storage?.images?.[name]?.complete) {
                throw new Error("Image indisponible ou transfert incomplet.");
            }
            // L'ancienne image de transfert ne doit jamais être sélectionnée.
            try {
                const response = await fetch("/extras/wifi-wizard/api/usb-transfer/status", {
                    cache: "no-store", credentials: "same-origin",
                });
                if (response.ok) {
                    const st = (await response.json()).transfer;
                    if (st?.drive?.transfer_active || ["starting", "stopping", "importing", "preparing", "connected"].includes(st?.state)) {
                        throw new Error("Le mode transfert USB est actif.");
                    }
                }
            } catch (error) {
                if (error.message === "Le mode transfert USB est actif.") throw error;
            }
            const cdrom = !name || name.toLowerCase().endsWith(".iso") ? "1" : "0";
            await api("/api/msd/set_params?" + new URLSearchParams({image: name, cdrom, rw: "0"}), {method: "POST"});
            panel.hidden = true;
            await refresh();
        } catch (error) {
            alert("Impossible de sélectionner l'image :\n" + error.message);
        } finally {
            inFlight = false;
            draw();
        }
    }

    launch.addEventListener("click", async () => {
        panel.hidden = !panel.hidden;
        if (!panel.hidden) {
            // Désactive tout filtre historique de PiKVM qui masquerait les fichiers sélectionnés.
            if (filter && filter.value) {
                filter.value = "";
                filter.dispatchEvent(new Event("input", {bubbles: true}));
            }
            await refresh();
        }
    });
    search.addEventListener("input", draw);
    document.addEventListener("click", event => {
        if (!browser.contains(event.target)) panel.hidden = true;
    });


    // Navigateur indépendant du menu déroulant Drive.
    const overlay = document.createElement("div");
    overlay.id = "pkdf-overlay";
    overlay.hidden = true;

    document.body.append(overlay);
    overlay.append(panel);

    const modalStyle = document.createElement("style");

    modalStyle.textContent = `
        #pkdf-overlay {
            position: fixed;
            inset: 0;
            z-index: 2147483200;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 12px;
            background: rgba(0, 0, 0, .7);
        }

        #pkdf-overlay[hidden] {
            display: none !important;
        }

        #pkdf-overlay > #pkdf-panel {
            width: min(600px, 100%);
            max-height: min(630px, 90vh);
            display: flex;
            flex-direction: column;
            margin: 0;
            overflow: hidden;
            box-shadow: 0 10px 30px #000b;
        }

        #pkdf-overlay #pkdf-items {
            max-height: none;
            min-height: 0;
            overflow-y: auto;
        }
    `;

    document.head.append(modalStyle);

    // Conserve le comportement de la V1 pour ouvrir
    // et fermer le navigateur.
    new MutationObserver(() => {
        overlay.hidden = panel.hidden;
    }).observe(panel, {
        attributes: true,
        attributeFilter: ["hidden"]
    });

    // Les clics dans la fenêtre ne doivent pas
    // déclencher sa fermeture automatique.
    overlay.addEventListener("click", (event) => {
        event.stopPropagation();

        if (event.target === overlay) {
            panel.hidden = true;
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            panel.hidden = true;
        }
    });

    // Masquage limité aux contrôles de sélection : le reste de Drive est natif.
    selector.style.display = "none";
    if (filterRow) filterRow.style.display = "none";
    refresh();
    setInterval(() => {
        if (menu.getClientRects().length && !document.hidden) refresh();
    }, 4000);
})();

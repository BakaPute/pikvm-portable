"use strict";

// Extension du gestionnaire existant. N'interfère pas avec USB-TRANSFER.
(() => {
    let folders = [];
    let current = "";
    let actionInProgress = false;
    const api = "/extras/image-manager/api/image-manager/folders";
    window.pikvmImageCurrentFolder = "";

    const folderPane = document.createElement("div");
    folderPane.id = "im-folders";
    document.getElementById("imageList").before(folderPane);

    function parentOf(path) {
        const pos = path.lastIndexOf("/");
        return pos === -1 ? "" : path.slice(0, pos);
    }
    function basename(path) { return path.split("/").pop(); }
    function canEdit() {
        return !actionInProgress && !browserUploadActive &&
            !msdState?.busy && !msdState?.drive?.connected &&
            !msdState?.storage?.uploading && !usbBusy();
    }
    async function folderRequest(action, data = {}) {
        const response = await managerPost("image-manager/folders/action", {action, ...data});
        return response.result || {};
    }
    async function clearSelectedIfNeeded(path, isFolder = false) {
        const selected = selectedName();
        if (selected && (selected === path || (isFolder && selected.startsWith(path + "/")))) {
            await nativePost("/api/msd/set_params", {image: "", cdrom: 1, rw: 0});
        }
    }
    async function perform(action, data, selectedPath = null, isFolder = false) {
        if (!canEdit()) {
            showToast("Stockage occupé : attends la fin du transfert ou déconnecte Drive.", true);
            return null;
        }
        actionInProgress = true;
        try {
            if (selectedPath) await clearSelectedIfNeeded(selectedPath, isFolder);
            const result = await folderRequest(action, data);
            await refreshFolders();
            await loadAll();
            showToast("Modification enregistrée");
            return result;
        } catch (err) {
            showToast(err.message, true);
            return null;
        } finally {
            actionInProgress = false;
        }
    }
    function openFolder(path) {
        current = path;
        window.pikvmImageCurrentFolder = current;
        renderFolders();
        renderImages();
    }
    function folderButton(text, onClick, className = "button small") {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = className;
        btn.textContent = text;
        btn.addEventListener("click", onClick);
        return btn;
    }
    function renderFolders() {
        const crumbs = document.createElement("div");
        crumbs.className = "im-crumbs";
        crumbs.append(folderButton("Stockage /", () => openFolder("")));
        let path = "";
        for (const part of current.split("/").filter(Boolean)) {
            path = path ? path + "/" + part : part;
            const dest = path;
            crumbs.append(folderButton(part, () => openFolder(dest)));
        }
        const toolbar = document.createElement("div");
        toolbar.className = "im-toolbar";
        toolbar.append(folderButton("+ Nouveau dossier", async () => {
            const name = prompt("Nom du nouveau dossier :");
            if (name === null) return;
            await perform("mkdir", {parent: current, name: name.trim()});
        }, "button primary small"));
        if (current) toolbar.append(folderButton("↑ Dossier parent", () => openFolder(parentOf(current))));
        const entries = document.createElement("div");
        entries.className = "im-folder-grid";
        const directChildren = folders.filter(name => parentOf(name) === current);
        for (const folder of directChildren) {
            const card = document.createElement("div");
            card.className = "im-folder-card";
            const name = document.createElement("div");
            name.className = "im-folder-title";
            name.textContent = "📁 " + basename(folder);
            const actions = document.createElement("div");
            actions.className = "im-folder-actions";
            actions.append(folderButton("Ouvrir", () => openFolder(folder)));
            actions.append(folderButton("Renommer", async () => {
                const next = prompt("Nouveau nom du dossier :", basename(folder));
                if (next === null || next.trim() === basename(folder)) return;
                const result = await perform("rename_dir", {path: folder, name: next.trim()}, folder, true);
                if (result && current.startsWith(folder + "/")) {
                    openFolder(result.path + current.slice(folder.length));
                } else if (result && current === folder) {
                    openFolder(result.path);
                }
            }));
            actions.append(folderButton("Supprimer", async () => {
                if (!confirm(`Supprimer le dossier vide « ${folder} » ?\n\nAucun dossier contenant des fichiers ne sera supprimé.`)) return;
                await perform("rmdir", {path: folder}, folder, true);
            }, "button red small"));
            card.append(name, actions);
            entries.append(card);
        }
        folderPane.replaceChildren(crumbs, toolbar, entries);
    }
    async function refreshFolders() {
        try {
            const response = await jsonRequest(api);
            folders = response.result?.folders || [];
            if (current && !folders.includes(current)) {
                current = "";
                window.pikvmImageCurrentFolder = "";
            }
            renderFolders();
            if (msdState) renderImages();
        } catch (err) {
            showToast("Dossiers : " + err.message, true);
        }
    }
    function chooseFolder() {
        return new Promise(resolve => {
            const overlay = document.createElement("div");
            overlay.className = "im-overlay";
            const panel = document.createElement("div");
            panel.className = "im-modal";
            const heading = document.createElement("h3");
            heading.textContent = "Déplacer dans un dossier";
            const select = document.createElement("select");
            for (const folder of ["", ...folders]) {
                const option = document.createElement("option");
                option.value = folder;
                option.textContent = folder || "Racine du stockage";
                select.append(option);
            }
            select.value = current;
            const buttons = document.createElement("div");
            buttons.className = "im-folder-actions";
            const finish = (choice) => { overlay.remove(); resolve(choice); };
            buttons.append(folderButton("Annuler", () => finish(null)));
            buttons.append(folderButton("Déplacer", () => finish(select.value), "button primary small"));
            panel.append(heading, select, buttons);
            overlay.append(panel);
            overlay.addEventListener("click", (e) => { if (e.target === overlay) finish(null); });
            document.body.append(overlay);
            select.focus();
        });
    }
    // Filtrage sans modifier la structure de l'API PiKVM.
    const originalRenderImages = renderImages;
    renderImages = function() {
        if (!msdState?.storage?.images) return originalRenderImages();
        const saved = msdState;
        const images = Object.fromEntries(Object.entries(saved.storage.images)
            .filter(([path]) => parentOf(path) === current));
        msdState = {...saved, storage: {...saved.storage, images}};
        try { originalRenderImages(); } finally { msdState = saved; }
        const list = document.getElementById("imageList");
        list.querySelectorAll(".image-card").forEach(card => {
            const useBtn = card.querySelector('button[data-action="use"]');
            if (!useBtn) return;
            const path = decodeURIComponent(useBtn.dataset.name);
            const info = saved.storage.images[path];
            const buttons = card.querySelector(".image-actions");
            if (!buttons) return;
            const moving = folderButton("Déplacer", async () => {
                const destination = await chooseFolder();
                if (destination === null || destination === parentOf(path)) return;
                await perform("move_file", {source: path, folder: destination}, path);
            });
            moving.disabled = !canEdit() || !info?.complete;
            buttons.append(moving);
            if (!info?.complete) {
                card.querySelectorAll('button[data-action]').forEach(b => { b.disabled = true; });
                const label = document.createElement("span");
                label.className = "badge";
                label.textContent = "Import incomplet";
                card.querySelector(".image-meta")?.append(label);
            }
        });
    };

    // La fonction existante gère mal les chemins imbriqués à cause du renommage racine.
    renameImage = async function(path) {
        if (!canEdit()) {
            showToast("Drive occupé.", true);
            return;
        }
        const file = basename(path);
        const extension = file.slice(file.lastIndexOf("."));
        const proposed = prompt("Nouveau nom :", file.slice(0, -extension.length));
        if (proposed === null || !proposed.trim()) return;
        let name = proposed.trim();
        if (!name.toLowerCase().endsWith(extension.toLowerCase())) name += extension;
        if (name === file) return;
        await perform("rename_file", {source: path, name}, path);
    };

    // La fonction loadAll() existante continue de gérer les images et la capacité.
    refreshFolders();
    setInterval(refreshFolders, 6000);
})();

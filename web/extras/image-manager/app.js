"use strict";

const MANAGER_API =
    "/extras/image-manager/api";

let msdState = null;
let usbState = null;
let loading = false;
let browserUploadActive = false;
let browserUploadKeepUntil = 0;
let activeUploadXhr = null;
let uploadCancelled = false;

// ============================================================
// PROTECTION CONTRE LA FERMETURE PENDANT UN UPLOAD
// ============================================================

window.addEventListener("beforeunload", (event) => {

    // Aucun transfert navigateur en cours :
    // navigation autorisée normalement.
    if (!browserUploadActive) {
        return;
    }

    // Upload en cours :
    // demande confirmation avant de quitter la page.
    event.preventDefault();

    // Nécessaire pour certains navigateurs.
    event.returnValue = "";

});





function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function formatBytes(bytes) {

    bytes = Number(bytes || 0);

    const units = [
        "o",
        "Kio",
        "Mio",
        "Gio",
        "Tio"
    ];

    let index = 0;

    while (
        bytes >= 1024
        && index < units.length - 1
    ) {
        bytes /= 1024;
        index++;
    }

    return (
        bytes.toFixed(
            index >= 3 ? 2 : 1
        )
        + " "
        + units[index]
    );
}


function imageType(name) {

    const dot =
        name.lastIndexOf(".");

    if (dot < 0) {
        return "IMAGE";
    }

    return (
        name.slice(dot + 1)
        .toUpperCase()
    );
}


function showToast(
    message,
    error = false
) {

    const toast =
        document.getElementById(
            "toast"
        );

    toast.textContent =
        message;

    toast.className =
        "toast show"
        + (error ? " error" : "");

    clearTimeout(
        showToast.timer
    );

    showToast.timer =
        setTimeout(
            () => {
                toast.className =
                    "toast";
            },
            3500
        );
}


async function jsonRequest(
    url,
    options = {}
) {

    const response =
        await fetch(
            url,
            {
                credentials:
                    "same-origin",

                cache:
                    "no-store",

                ...options
            }
        );

    let data = {};

    try {
        data =
            await response.json();
    }
    catch (_) {
    }

    if (
        !response.ok
        || data.ok === false
    ) {
        throw new Error(
            data.result?.error_msg
            || data.error
            || data.message
            || `HTTP ${response.status}`
        );
    }

    return data;
}


async function nativeMsd() {

    const data =
        await jsonRequest(
            "/api/msd"
        );

    return data.result;
}


async function nativePost(
    path,
    params = {}
) {

    const query =
        new URLSearchParams(
            params
        );

    return jsonRequest(
        path
        + "?"
        + query.toString(),
        {
            method: "POST"
        }
    );
}


async function managerPost(
    path,
    body = {}
) {

    return jsonRequest(
        MANAGER_API
        + "/"
        + path,
        {
            method: "POST",

            headers: {
                "Content-Type":
                    "application/json"
            },

            body:
                JSON.stringify(body)
        }
    );
}


async function usbStatus() {

    const data =
        await jsonRequest(
            MANAGER_API
            + "/usb-transfer/status"
        );

    return data.transfer;
}


function selectedName() {

    return (
        msdState
        ?.drive
        ?.image
        ?.name
        || null
    );
}


function usbBusy() {

    if (!usbState) {
        return false;
    }

    const state =
        usbState.state;

    return (
        usbState
            ?.drive
            ?.transfer_active
        || [
            "starting",
            "connected",
            "stopping",
            "importing",
            "preparing"
        ].includes(state)
    );
}


function renderStorage() {

    const part =
        msdState
        ?.storage
        ?.parts
        ?.[""];

    if (!part) {
        return;
    }

    const size =
        Number(part.size || 0);

    const free =
        Number(part.free || 0);

    const used =
        Math.max(
            0,
            size - free
        );

    const ratio =
        size
        ? used / size
        : 0;


    document.getElementById(
        "storageText"
    ).textContent =
        `${formatBytes(used)} utilisés / ${formatBytes(size)}`;


    document.getElementById(
        "storageFree"
    ).textContent =
        `${formatBytes(free)} libres`;


    document.getElementById(
        "storageFill"
    ).style.width =
        `${Math.min(100, ratio * 100)}%`;
}


function renderUsb() {
    if (
        browserUploadActive
        || Date.now() < browserUploadKeepUntil
    ) {
        return;
    }


    const box =
        document.getElementById(
            "operationBox"
        );

    const text =
        document.getElementById(
            "operationText"
        );

    const fill =
        document.getElementById(
            "operationFill"
        );

    const start =
        document.getElementById(
            "usbStart"
        );

    const finish =
        document.getElementById(
            "usbFinish"
        );

    const upload =
        document.getElementById(
            "uploadButton"
        );


    const state =
        usbState?.state
        || "idle";

    const active =
        Boolean(
            usbState
            ?.drive
            ?.transfer_active
        );

    const operating = [
        "starting",
        "stopping",
        "importing",
        "preparing"
    ].includes(state);


    start.disabled =
        active
        || operating
        || Boolean(
            msdState
            ?.drive
            ?.connected
        );


    finish.disabled =
        !active;


    upload.disabled =
        active
        || operating
        || Boolean(
            msdState
            ?.drive
            ?.connected
        );


    let message = "";
    let percent = null;


    if (active) {

        message =
            "PIKVM-XFER connecté au PC";

    }
    else if (
        state === "importing"
    ) {

        percent =
            Number(
                usbState.percent
                ?? 0
            );

        message =
            usbState.message
            || "Import en cours...";

        message +=
            ` — ${Math.round(percent)} %`;


        if (usbState.total) {

            message +=
                ` (${usbState.done || 0}/${usbState.total})`;
        }

    }
    else if (
        state === "starting"
        || state === "stopping"
        || state === "preparing"
    ) {

        message =
            usbState.message
            || "Opération USB...";

    }
    else if (
        state === "done"
    ) {

        message =
            usbState.message
            || "Import terminé";

        percent = 100;

    }
    else if (
        state === "error"
    ) {

        message =
            "Erreur USB : "
            + (
                usbState.message
                || "inconnue"
            );
    }


    if (message) {

        box.hidden = false;
        text.textContent = message;

        fill.style.width =
            percent === null
            ? "0%"
            : `${Math.max(
                0,
                Math.min(
                    100,
                    percent
                )
            )}%`;

    }
    else {

        box.hidden = true;
        fill.style.width = "0%";
    }
}


function renderImages() {

    const list =
        document.getElementById(
            "imageList"
        );

    const images =
        Object.entries(
            msdState
            ?.storage
            ?.images
            || {}
        );

    images.sort(
        (a, b) =>
            a[0].localeCompare(
                b[0],
                "fr",
                {
                    sensitivity:
                        "base"
                }
            )
    );


    document.getElementById(
        "imageCount"
    ).textContent =
        images.length;


    if (!images.length) {

        list.innerHTML = `
            <div class="empty">
                Aucune image ISO / IMG / RAW
            </div>
        `;

        return;
    }


    const selected =
        selectedName();

    const connected =
        Boolean(
            msdState
            ?.drive
            ?.connected
        );

    const blocked =
        connected
        || usbBusy()
        || browserUploadActive
        || Boolean(msdState?.busy)
        || Boolean(msdState?.storage?.uploading);


    list.innerHTML =
        images.map(
            ([name, info]) => {

                const isSelected =
                    selected === name;

                const isConnected =
                    isSelected
                    && connected;

                const date =
                    info.mod_ts
                    ? new Date(
                        info.mod_ts * 1000
                    ).toLocaleString(
                        "fr-FR"
                    )
                    : "-";


                let badges = "";


                if (isConnected) {

                    badges += `
                        <span class="badge connected">
                            Connectée
                        </span>
                    `;

                }
                else if (isSelected) {

                    badges += `
                        <span class="badge selected">
                            Sélectionnée
                        </span>
                    `;
                }


                return `
                    <article class="image-card">

                        <div class="image-top">

                            <div>

                                <div class="image-name">
                                    ${escapeHtml(name)}
                                </div>

                                <div class="image-meta">

                                    <span>
                                        ${escapeHtml(imageType(name))}
                                    </span>

                                    <span>
                                        ${formatBytes(info.size)}
                                    </span>

                                    <span>
                                        ${escapeHtml(date)}
                                    </span>

                                </div>

                            </div>

                            <div>
                                ${badges}
                            </div>

                        </div>


                        <div class="image-actions">

                            <button
                                class="button small"
                                data-action="use"
                                data-name="${encodeURIComponent(name)}"
                                ${blocked ? "disabled" : ""}
                            >
                                Utiliser dans Drive
                            </button>

                            <button
                                class="button small"
                                data-action="rename"
                                data-name="${encodeURIComponent(name)}"
                                ${blocked ? "disabled" : ""}
                            >
                                Renommer
                            </button>

                            <button
                                class="button red small"
                                data-action="delete"
                                data-name="${encodeURIComponent(name)}"
                                ${blocked ? "disabled" : ""}
                            >
                                Supprimer
                            </button>

                        </div>

                    </article>
                `;
            }
        ).join("");


    list
        .querySelectorAll(
            "button[data-action]"
        )
        .forEach(
            button => {

                button.addEventListener(
                    "click",
                    () => {

                        const name =
                            decodeURIComponent(
                                button.dataset.name
                            );

                        const action =
                            button.dataset.action;


                        if (action === "use") {
                            useImage(name);
                        }
                        else if (
                            action === "rename"
                        ) {
                            renameImage(name);
                        }
                        else if (
                            action === "delete"
                        ) {
                            deleteImage(name);
                        }

                    }
                );
            }
        );
}


async function loadAll() {

    if (loading) {
        return;
    }

    loading = true;

    try {

        const results =
            await Promise.all([
                nativeMsd(),
                usbStatus()
            ]);

        msdState =
            results[0];

        usbState =
            results[1];

        renderStorage();
        renderUsb();
        renderImages();

    }
    catch (error) {

        showToast(
            error.message,
            true
        );

    }
    finally {

        loading = false;
    }
}


async function useImage(name) {

    try {
        msdState = await nativeMsd();
        usbState = await usbStatus();
    }
    catch (error) {
        showToast(error.message, true);
        return;
    }

    if (msdState.busy || usbBusy()) {
        showToast(
            "Drive occupé : réessaie dans quelques secondes.",
            true
        );
        return;
    }

    if (
        msdState
        ?.drive
        ?.connected
    ) {

        showToast(
            "Déconnecte d'abord le Drive.",
            true
        );

        return;
    }


    const cdrom =
        name
        .toLowerCase()
        .endsWith(".iso")
        ? "1"
        : "0";


    try {

        await nativePost(
            "/api/msd/set_params",
            {
                image: name,
                cdrom,
                rw: "0"
            }
        );

        showToast(
            `${name} sélectionnée dans Drive`
        );

        await loadAll();

    }
    catch (error) {

        showToast(
            error.message,
            true
        );
    }
}


async function renameImage(name) {

    if (
        msdState
        ?.drive
        ?.connected
        || usbBusy()
    ) {
        return;
    }


    const dot =
        name.lastIndexOf(".");

    const extension =
        dot >= 0
        ? name.slice(dot)
        : "";

    const base =
        dot >= 0
        ? name.slice(0, dot)
        : name;


    let newName =
        prompt(
            "Nouveau nom :",
            base
        );


    if (newName === null) {
        return;
    }


    newName =
        newName.trim();


    if (!newName) {
        return;
    }


    if (
        !newName
        .toLowerCase()
        .endsWith(
            extension.toLowerCase()
        )
    ) {
        newName += extension;
    }


    const wasSelected =
        selectedName() === name;


    try {

        if (wasSelected) {

            await nativePost(
                "/api/msd/set_params",
                {
                    image: ""
                }
            );
        }


        await managerPost(
            "image-manager/rename",
            {
                old_name: name,
                new_name: newName
            }
        );


        if (wasSelected) {

            const cdrom =
                newName
                .toLowerCase()
                .endsWith(".iso")
                ? "1"
                : "0";

            await nativePost(
                "/api/msd/set_params",
                {
                    image:
                        newName,

                    cdrom,

                    rw:
                        "0"
                }
            );
        }


        showToast(
            "Image renommée"
        );

        await loadAll();

    }
    catch (error) {

        showToast(
            error.message,
            true
        );
    }
}


async function deleteImage(name) {

    if (
        msdState
        ?.drive
        ?.connected
        || usbBusy()
    ) {
        return;
    }


    if (
        !confirm(
            `Supprimer définitivement :\n\n${name} ?`
        )
    ) {
        return;
    }


    const wasSelected =
        selectedName() === name;


    try {

        if (wasSelected) {

            await nativePost(
                "/api/msd/set_params",
                {
                    image: ""
                }
            );
        }


        await nativePost(
            "/api/msd/remove",
            {
                image: name
            }
        );


        showToast(
            `${name} supprimée`
        );

        await loadAll();

    }
    catch (error) {

        showToast(
            error.message,
            true
        );
    }
}


function uploadOne(file) {

    return new Promise(
        (resolve, reject) => {

            const box =
                document.getElementById(
                    "operationBox"
                );

            const text =
                document.getElementById(
                    "operationText"
                );

            const fill =
                document.getElementById(
                    "operationFill"
                );


            box.hidden = false;


            const xhr =
                new XMLHttpRequest();

            activeUploadXhr = xhr;

            xhr.addEventListener("loadend", () => {
                if (activeUploadXhr === xhr) {
                    activeUploadXhr = null;
                }
            });

            xhr.addEventListener("abort", () => {
                reject(new Error("Transfert annulé"));
            });


            const query =
                new URLSearchParams({
                    image:
                        file.name,
                    prefix:
                        window.pikvmImageCurrentFolder || "",

                    remove_incomplete:
                        "1"
                });


            xhr.open(
                "POST",
                "/api/msd/write?"
                + query.toString()
            );


            xhr.withCredentials =
                true;


            xhr.setRequestHeader(
                "Content-Type",
                "application/octet-stream"
            );


            xhr.upload.onprogress =
                event => {

                    if (!event.lengthComputable) {
                        return;
                    }

                    const percent =
                        event.loaded
                        * 100
                        / event.total;

                    text.textContent =
                        `Upload ${file.name} — ${Math.round(percent)} %`;

                    fill.style.width =
                        `${percent}%`;
                };


            xhr.onload = () => {

                if (
                    xhr.status >= 200
                    && xhr.status < 300
                ) {
                    resolve();
                }
                else {
                    reject(
                        new Error(
                            `Erreur upload HTTP ${xhr.status}`
                        )
                    );
                }
            };


            xhr.onerror = () => {

                reject(
                    new Error(
                        "Erreur réseau pendant l'upload."
                    )
                );
            };


            xhr.send(file);
        }
    );
}


async function uploadFiles(files) {

    if (
        msdState
        ?.drive
        ?.connected
        || usbBusy()
    ) {

        showToast(
            "Drive ou transfert USB occupé.",
            true
        );

        return;
    }


    browserUploadActive = true;
    uploadCancelled = false;

    cancelUploadButton.hidden = false;
    cancelUploadButton.disabled = false;
    cancelUploadButton.textContent = "Annuler le transfert";

    document.getElementById("uploadButton").disabled = true;
    document.getElementById("usbStart").disabled = true;

    try {

        for (
            let index = 0;
            index < files.length;
            index++
        ) {

            if (uploadCancelled) {
                throw new Error("Transfert annulé");
            }

            const file =
                files[index];

            const lower =
                file.name.toLowerCase();


            if (
                !lower.endsWith(".iso")
                && !lower.endsWith(".img")
                && !lower.endsWith(".raw")
            ) {

                throw new Error(
                    `Format non pris en charge : ${file.name}`
                );
            }


            await uploadOne(file);
        }


        if (uploadCancelled) {
            throw new Error("Transfert annulé");
        }

        showToast(
            `${files.length} image(s) importée(s)`
        );


        const box = document.getElementById("operationBox");
        const text = document.getElementById("operationText");
        const fill = document.getElementById("operationFill");

        box.hidden = false;
        text.textContent = `${files.length} image(s) importée(s)`;
        fill.style.width = "100%";

        browserUploadKeepUntil = Date.now() + 8000;

        await loadAll();


    }
    catch (error) {

        const text = document.getElementById("operationText");
        const fill = document.getElementById("operationFill");

        if (uploadCancelled) {
            text.textContent =
                "Transfert annulé — nettoyage de l'image incomplète";
            fill.style.width = "0%";
            showToast("Transfert annulé");
        } else {
            text.textContent = "Erreur : " + error.message;
            showToast(error.message, true);
        }

        browserUploadKeepUntil = Date.now() + 6000;
    }
    finally {
        browserUploadActive = false;
        activeUploadXhr = null;

        cancelUploadButton.hidden = true;
        cancelUploadButton.disabled = false;

        document.getElementById("uploadButton").disabled = false;
        document.getElementById("usbStart").disabled = false;

        setTimeout(loadAll, 100);
    }

}


async function startUsbTransfer() {

    try {

        await managerPost(
            "usb-transfer/start"
        );

        showToast(
            "PIKVM-XFER connecté"
        );

        await loadAll();

    }
    catch (error) {

        showToast(
            error.message,
            true
        );
    }
}


async function finishUsbTransfer() {

    if (
        !confirm(
            "Éjecte d'abord PIKVM-XFER dans Windows.\n\n"
            + "Lancer ensuite l'import ?"
        )
    ) {
        return;
    }


    try {

        await managerPost(
            "usb-transfer/import"
        );

        showToast(
            "Import USB lancé"
        );

        await loadAll();

    }
    catch (error) {

        showToast(
            error.message,
            true
        );
    }
}


async function logoutPikvm() {

    try {

        await fetch(
            "/auth/logout",
            {
                method: "POST",
                credentials:
                    "same-origin",
                cache:
                    "no-store"
            }
        );

    }
    catch (_) {
    }

    window.location.href =
        "/login/";
}


document
    .getElementById(
        "refreshButton"
    )
    .addEventListener(
        "click",
        loadAll
    );


document
    .getElementById(
        "uploadButton"
    )
    .addEventListener(
        "click",
        () => {

            document
                .getElementById(
                    "fileInput"
                )
                .click();
        }
    );


document
    .getElementById(
        "fileInput"
    )
    .addEventListener(
        "change",
        event => {

            const files =
                Array.from(
                    event.target.files
                    || []
                );

            if (files.length) {
                uploadFiles(files);
            }

            event.target.value = "";
        }
    );


document
    .getElementById(
        "usbStart"
    )
    .addEventListener(
        "click",
        startUsbTransfer
    );


document
    .getElementById(
        "usbFinish"
    )
    .addEventListener(
        "click",
        finishUsbTransfer
    );



// ============================================================
// BOUTON ANNULER L'UPLOAD NAVIGATEUR
// ============================================================

const cancelUploadButton = document.createElement("button");

cancelUploadButton.id = "cancelUploadButton";
cancelUploadButton.type = "button";
cancelUploadButton.className = "button red small";
cancelUploadButton.textContent = "Annuler le transfert";
cancelUploadButton.style.marginTop = "10px";
cancelUploadButton.hidden = true;

document.getElementById("operationBox").appendChild(
    cancelUploadButton
);

cancelUploadButton.addEventListener("click", () => {

    if (!browserUploadActive || uploadCancelled) {
        return;
    }

    if (!confirm(
        "Annuler le transfert en cours ?\n\n" +
        "L'image partiellement envoyée sera supprimée."
    )) {
        return;
    }

    uploadCancelled = true;

    cancelUploadButton.disabled = true;
    cancelUploadButton.textContent = "Annulation...";

    document.getElementById("operationText").textContent =
        "Annulation du transfert...";

    if (activeUploadXhr) {
        activeUploadXhr.abort();
    }
});


loadAll();

setInterval(
    loadAll,
    2000
);

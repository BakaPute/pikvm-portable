export function el(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (value === undefined || value === null) continue;
        if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
        else if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key in node && !key.startsWith('aria')) node[key] = value;
        else node.setAttribute(key, value);
    }
    for (const child of children.flat(Infinity)) if (child !== undefined && child !== null)
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
}
export function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('class', 'icon');
    const use = document.createElementNS(svg.namespaceURI, 'use');
    use.setAttribute('href', '/extras/portable-os/icons.svg#' + name); svg.append(use); return svg;
}
export const button = (text, action, kind = '', attrs = {}) => el('button', {type: 'button', class: kind, onclick: action, ...attrs}, text);
export const badge = (text, tone = '') => el('span', {class: 'badge ' + tone}, text);
export const card = (title, ...children) => el('section', {class: 'card'}, el('h2', {}, title), ...children);
export const row = (...children) => el('div', {class: 'row'}, ...children);
export const hint = text => el('p', {class: 'muted'}, text);
export const field = (title, input) => el('label', {class: 'field'}, el('span', {}, title), input);
export function empty(text) { return el('div', {class: 'empty'}, icon('storage'), el('p', {}, text)); }
export function table(headers, rows) {
    return el('div', {class: 'table-scroll'}, el('table', {},
        el('thead', {}, el('tr', {}, headers.map(title => el('th', {scope: 'col'}, title)))),
        el('tbody', {}, rows.map(cells => el('tr', {}, cells.map(value => el('td', {}, value)))))));
}
export function notify(message, danger = false) {
    const node = el('div', {class: 'toast ' + (danger ? 'danger' : ''), role: danger ? 'alert' : 'status'},
        icon(danger ? 'alert' : 'check'), el('span', {}, message));
    document.getElementById('notifications').append(node);
    setTimeout(() => node.remove(), danger ? 10000 : 5000);
}
export async function dialog({title, message, fields = [], confirm = 'Confirmer', danger = false}) {
    const host = document.getElementById('dialogs');
    if (host.childElementCount) throw new Error('Une boîte de dialogue est déjà ouverte.');
    const previous = document.activeElement;
    return new Promise(resolve => {
        const inputs = {};
        const close = value => { node.close(); node.remove(); previous?.focus(); resolve(value); };
        const form = el('form', {onsubmit: event => {
            event.preventDefault();
            if (!form.reportValidity()) return;
            close(Object.fromEntries(Object.entries(inputs).map(([name, input]) =>
                [name, input.type === 'checkbox' ? input.checked : input.value])));
        }}, el('h2', {id: 'dialog-title'}, title), hint(message));
        for (const spec of fields) {
            const select = spec.type === 'select';
            const attributes = {name: spec.name, required: spec.required !== false,
                autocomplete: spec.type === 'password' ? 'new-password' : 'off'};
            if (!select) attributes.type = spec.type || 'text';
            const input = el(select ? 'select' : 'input', attributes);
            if (spec.options) for (const option of spec.options) input.append(el('option', {value: option}, option || '/'));
            if (spec.type === 'checkbox') input.checked = spec.value === true;
            else input.value = spec.value ?? (select ? input.value : '');
            inputs[spec.name] = input; form.append(field(spec.label, input));
        }
        form.append(el('div', {class: 'dialog-actions'}, button('Annuler', () => close(null), 'quiet'),
            el('button', {type: 'submit', class: danger ? 'danger' : 'primary'}, confirm)));
        const node = el('dialog', {'aria-labelledby': 'dialog-title', oncancel: event => { event.preventDefault(); close(null); }}, form);
        host.append(node); node.showModal();
    });
}
export async function guarded(work) { try { return await work(); } catch (error) { notify(error.message, true); return undefined; } }

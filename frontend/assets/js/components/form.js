/**
 * MADMIN - Form Component
 *
 * Declarative form fields in the Tabler style: render, read, validate.
 *
 * Semi-public: stable path /static/js/components/form.js — modules may adopt
 * it. Exports are additive-only once shipped.
 *
 * Field spec:
 * {
 *   name: string,                  // required, unique within the form
 *   label: string,                 // escaped
 *   type: 'text'|'password'|'number'|'email'|'url'|'select'|'checkbox'|'switch'|'textarea'|'color',
 *   value: any,                    // initial value
 *   placeholder: string,
 *   hint: string,                  // form-hint under the field (escaped)
 *   required: boolean,
 *   disabled: boolean,
 *   options: [{ value, label }],   // select only (escaped)
 *   attrs: { key: value },         // extra HTML attributes (escaped)
 *   validate: (value, allValues) => true | string,  // string = error message
 * }
 */

import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

function _attrString(attrs = {}) {
    return Object.entries(attrs)
        .map(([k, v]) => `${escapeHtml(k)}="${escapeHtml(String(v))}"`)
        .join(' ');
}

function _fieldId(field) {
    return `field-${field.name}`;
}

/**
 * Render field specs to HTML. All text options are escaped.
 * @param {Array} fields
 * @param {Object} [opts]
 * @param {number} [opts.columns] - 1 (stacked) or 2 (row of col-md-6)
 * @returns {string}
 */
export function renderFields(fields, { columns = 1 } = {}) {
    const rendered = fields.map((field) => {
        const id = _fieldId(field);
        const required = field.required ? ' required' : '';
        const disabled = field.disabled ? ' disabled' : '';
        const extra = _attrString(field.attrs);
        const value = field.value ?? '';
        let control;

        switch (field.type) {
            case 'select':
                control = `
                    <select class="form-select" id="${id}" name="${escapeHtml(field.name)}"${required}${disabled} ${extra}>
                        ${(field.options || []).map(o => `
                            <option value="${escapeHtml(String(o.value))}" ${String(o.value) === String(value) ? 'selected' : ''}>${escapeHtml(o.label)}</option>
                        `).join('')}
                    </select>`;
                break;
            case 'checkbox':
            case 'switch':
                return `
                    <div class="mb-3">
                        <label class="form-check${field.type === 'switch' ? ' form-switch' : ''}">
                            <input type="checkbox" class="form-check-input" id="${id}" name="${escapeHtml(field.name)}"
                                   ${value ? 'checked' : ''}${disabled} ${extra}>
                            <span class="form-check-label">${escapeHtml(field.label)}</span>
                        </label>
                        ${field.hint ? `<small class="form-hint">${escapeHtml(field.hint)}</small>` : ''}
                    </div>`;
            case 'textarea':
                control = `
                    <textarea class="form-control" id="${id}" name="${escapeHtml(field.name)}" rows="${field.attrs?.rows || 3}"
                              placeholder="${escapeHtml(field.placeholder || '')}"${required}${disabled} ${extra}>${escapeHtml(String(value))}</textarea>`;
                break;
            case 'color':
                control = `
                    <input type="color" class="form-control form-control-color" id="${id}" name="${escapeHtml(field.name)}"
                           value="${escapeHtml(String(value))}"${disabled} ${extra}>`;
                break;
            default:
                control = `
                    <input type="${escapeHtml(field.type || 'text')}" class="form-control" id="${id}" name="${escapeHtml(field.name)}"
                           value="${escapeHtml(String(value))}" placeholder="${escapeHtml(field.placeholder || '')}"${required}${disabled} ${extra}>`;
        }

        return `
            <div class="mb-3">
                <label class="form-label${field.required ? ' required' : ''}" for="${id}">${escapeHtml(field.label)}</label>
                ${control}
                ${field.hint ? `<small class="form-hint">${escapeHtml(field.hint)}</small>` : ''}
                <div class="invalid-feedback"></div>
            </div>`;
    });

    if (columns === 2) {
        return `<div class="row">${rendered.map(html => `<div class="col-md-6">${html}</div>`).join('')}</div>`;
    }
    return rendered.join('');
}

/**
 * Read typed values from a rendered form.
 * checkbox/switch → boolean, number → Number (NaN-safe: empty → null).
 * @param {HTMLElement} rootEl
 * @param {Array} fields
 * @returns {Object}
 */
export function readForm(rootEl, fields) {
    const values = {};
    for (const field of fields) {
        const el = rootEl.querySelector(`#${_fieldId(field)}`);
        if (!el) continue;
        if (field.type === 'checkbox' || field.type === 'switch') {
            values[field.name] = el.checked;
        } else if (field.type === 'number') {
            values[field.name] = el.value === '' ? null : Number(el.value);
        } else {
            values[field.name] = el.value;
        }
    }
    return values;
}

/**
 * Validate a rendered form: required checks + per-field validate callbacks.
 * Applies .is-invalid and fills .invalid-feedback in the DOM.
 * @param {HTMLElement} rootEl
 * @param {Array} fields
 * @returns {{valid: boolean, values: Object, errors: Object}}
 */
export function validateForm(rootEl, fields) {
    clearFormErrors(rootEl);
    const values = readForm(rootEl, fields);
    const errors = {};

    for (const field of fields) {
        const value = values[field.name];
        if (field.required && (value === '' || value === null || value === undefined)) {
            errors[field.name] = t('common.requiredField');
            continue;
        }
        if (field.validate) {
            const res = field.validate(value, values);
            if (res !== true && res !== undefined) {
                errors[field.name] = typeof res === 'string' ? res : t('common.invalidValue');
            }
        }
    }

    setFormErrors(rootEl, errors);
    return { valid: Object.keys(errors).length === 0, values, errors };
}

/**
 * Apply error messages to fields: { fieldName: message }.
 * @param {HTMLElement} rootEl
 * @param {Object} errors
 */
export function setFormErrors(rootEl, errors) {
    for (const [name, message] of Object.entries(errors)) {
        const el = rootEl.querySelector(`#field-${name}`);
        if (!el) continue;
        el.classList.add('is-invalid');
        const feedback = el.closest('.mb-3')?.querySelector('.invalid-feedback');
        if (feedback) feedback.textContent = message;
    }
}

/**
 * Clear all validation errors from a rendered form.
 * @param {HTMLElement} rootEl
 */
export function clearFormErrors(rootEl) {
    rootEl.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid'));
    rootEl.querySelectorAll('.invalid-feedback').forEach(el => { el.textContent = ''; });
}

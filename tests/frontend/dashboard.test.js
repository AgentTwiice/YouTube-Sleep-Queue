const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class FakeElement {
    constructor(tag = 'div') {
        this.tag = tag;
        this.children = [];
        this.value = '';
        this.checked = false;
        this.style = {};
        this.className = '';
        this.textContent = '';
        this.classList = {add() {}, remove() {}, toggle() {}};
    }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.children.push(child); return child; }
    addEventListener() {}
    replaceChildren(...children) { this.children = children; }
}

function loadScript(name, fetchImpl) {
    const elements = new Map();
    const listeners = new Map();
    const document = {
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, new FakeElement());
            return elements.get(id);
        },
        createElement(tag) { return new FakeElement(tag); },
        createTextNode(value) { return {textContent: String(value)}; },
        addEventListener(event, callback) { listeners.set(event, callback); },
        querySelectorAll() { return []; },
        querySelector() { return new FakeElement(); }
    };
    const context = vm.createContext({
        window: {location: {origin: 'http://localhost', href: ''}},
        document,
        console,
        fetch: fetchImpl || (async () => { throw new Error('unexpected fetch'); }),
        setTimeout,
        clearTimeout,
        confirm: () => true
    });
    const source = fs.readFileSync(path.join(__dirname, '..', '..', 'dashboard', name), 'utf8');
    vm.runInContext(source, context, {filename: name});
    return {
        context,
        elements,
        trigger: async (event) => listeners.get(event)?.()
    };
}

test('channel rows keep hostile names and IDs as text', () => {
    const {context} = loadScript('channels.js');
    const hostile = `"><img src=x onerror=alert(1)>`;
    const row = context.createChannelRow({channel_id: hostile, title: hostile});
    const details = row.children[1];
    assert.equal(details.children[0].textContent, hostile);
    assert.equal(details.children[1].textContent, hostile);
    assert.equal(row.children.length, 2);
});

test('configuration form includes duration, date, keyword, and ranking fields', () => {
    const {context, elements} = loadScript('config.js');
    const set = (id, value) => { elements.get(id).value = value; };
    set('playlistName', 'Sleep');
    set('playlistVisibility', 'private');
    set('minDuration', '30');
    set('maxDuration', '600');
    elements.get('unlimitedDuration').checked = false;
    set('dateFilterMode', 'date_range');
    set('lookbackHours', '24');
    set('dateFilterDays', '7');
    set('dateFilterStart', '2026-07-01');
    set('dateFilterEnd', '2026-07-31');
    set('maxVideos', '25');
    elements.get('skipLiveContent').checked = true;
    set('ollamaBaseUrl', 'http://localhost:11434');
    set('ollamaModel', 'model');
    set('ollamaTimeout', '60');
    set('sleepMinimumScore', '75');
    set('sleepQueueSize', '8');
    set('keywordFilterMode', 'both');
    set('keywordInclude', 'calm\nrain');
    set('keywordExclude', 'news');
    set('keywordMatchType', 'all');
    elements.get('keywordCaseSensitive').checked = true;
    elements.get('keywordSearchDescription').checked = true;

    const config = context.getConfigFromForm();
    assert.equal(config.max_duration_seconds, 600);
    assert.equal(config.date_filter_mode, 'date_range');
    assert.equal(config.date_filter_start, '2026-07-01');
    assert.deepEqual(Array.from(config.keyword_include), ['calm', 'rain']);
    assert.deepEqual(Array.from(config.keyword_exclude), ['news']);
    assert.equal(config.keyword_match_type, 'all');
    assert.equal(config.keyword_search_description, true);
});

test('hostile API error strings remain text in configuration messages', () => {
    const {context, elements} = loadScript('config.js');
    const hostile = `<svg onload=alert('error')>`;
    context.showMessage(hostile, 'error');
    assert.equal(elements.get('message').textContent, hostile);
    assert.equal(elements.get('message').children.length, 0);
});

test('channel flow loads normalized configuration and subscriptions', async () => {
    const channelId = `UC${'a'.repeat(22)}`;
    const fetchImpl = async (url) => {
        if (url.endsWith('/csrf-token')) {
            return {ok: true, json: async () => ({csrf_token: 'csrf'})};
        }
        if (url.endsWith('/filter-config')) {
            return {ok: true, json: async () => ({
                success: true,
                filter_mode: 'allowlist',
                allowlist: [channelId],
                blocklist: []
            })};
        }
        if (url.endsWith('/channels')) {
            return {ok: true, json: async () => ({
                success: true,
                channels: [{channel_id: channelId, title: 'Quiet rain'}]
            })};
        }
        throw new Error(`unexpected URL ${url}`);
    };
    const {elements, trigger} = loadScript('channels.js', fetchImpl);
    await trigger('DOMContentLoaded');
    const rows = elements.get('channelList').children;
    assert.equal(rows.length, 1);
    assert.equal(rows[0].children[0].checked, true);
    assert.equal(rows[0].children[1].children[0].textContent, 'Quiet rain');
});

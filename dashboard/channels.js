const API_BASE = `${window.location.origin}/api`;
let csrfToken = null;
let channels = [];
let selected = new Set();
let currentMode = 'none';

const elements = {};

document.addEventListener('DOMContentLoaded', async () => {
    for (const id of ['statusMessage', 'searchSection', 'searchInput', 'channelsSection', 'channelListTitle', 'filterInfo', 'selectAllBtn', 'deselectAllBtn', 'channelList', 'cancelBtn', 'saveBtn']) {
        elements[id] = document.getElementById(id);
    }
    document.querySelectorAll('input[name="filterMode"]').forEach((radio) => radio.addEventListener('change', () => setMode(radio.value)));
    elements.searchInput.addEventListener('input', renderChannels);
    elements.selectAllBtn.addEventListener('click', () => {
        filteredChannels().forEach((channel) => selected.add(channel.channel_id));
        renderChannels();
    });
    elements.deselectAllBtn.addEventListener('click', () => {
        filteredChannels().forEach((channel) => selected.delete(channel.channel_id));
        renderChannels();
    });
    elements.cancelBtn.addEventListener('click', () => { window.location.href = 'config.html'; });
    elements.saveBtn.addEventListener('click', save);
    try {
        const tokenResponse = await fetch(`${API_BASE}/csrf-token`, {cache: 'no-store'});
        if (!tokenResponse.ok) throw new Error('Could not initialize request protection');
        csrfToken = (await tokenResponse.json()).csrf_token;
        await Promise.all([loadConfig(), loadChannels()]);
    } catch (error) {
        showStatus(error.message, 'error');
        showEmpty(error.message);
    }
});

async function loadConfig() {
    const response = await fetch(`${API_BASE}/channels/filter-config`, {cache: 'no-store'});
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.error || 'Could not load channel configuration');
    currentMode = result.filter_mode;
    selected = new Set(currentMode === 'allowlist' ? result.allowlist : result.blocklist);
    const radio = document.querySelector(`input[name="filterMode"][value="${currentMode}"]`);
    if (radio) radio.checked = true;
    updateModeUI();
}

async function loadChannels() {
    const response = await fetch(`${API_BASE}/channels`, {cache: 'no-store'});
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.error || 'Could not load subscriptions');
    channels = result.channels.map((channel) => ({
        channel_id: String(channel.channel_id || ''),
        title: String(channel.title || 'Unknown channel')
    }));
    renderChannels();
}

function setMode(mode) {
    if (!['none', 'allowlist', 'blocklist'].includes(mode)) return;
    currentMode = mode;
    selected.clear();
    updateModeUI();
    renderChannels();
}

function updateModeUI() {
    const active = currentMode !== 'none';
    elements.searchSection.style.display = active ? 'block' : 'none';
    elements.channelsSection.style.display = active ? 'block' : 'none';
    if (!active) return;
    elements.channelListTitle.textContent = currentMode === 'allowlist' ? 'Channels to include' : 'Channels to exclude';
    elements.filterInfo.replaceChildren();
    const strong = document.createElement('strong');
    strong.textContent = currentMode === 'allowlist' ? 'Allowlist mode: ' : 'Blocklist mode: ';
    const description = document.createTextNode(currentMode === 'allowlist'
        ? 'only selected channels are included.'
        : 'selected channels are excluded.');
    elements.filterInfo.append(strong, description);
}

function filteredChannels() {
    const query = elements.searchInput.value.trim().toLocaleLowerCase();
    if (!query) return channels;
    return channels.filter((channel) => channel.title.toLocaleLowerCase().includes(query) || channel.channel_id.toLocaleLowerCase().includes(query));
}

function renderChannels() {
    elements.channelList.replaceChildren();
    const visible = filteredChannels();
    if (!visible.length) {
        showEmpty(elements.searchInput.value ? 'No channels match this search.' : 'No subscriptions were returned.');
        return;
    }
    visible.forEach((channel) => elements.channelList.appendChild(createChannelRow(channel)));
}

function createChannelRow(channel) {
    const row = document.createElement('label');
    row.className = 'channel-item';
    if (selected.has(channel.channel_id)) row.classList.add('selected');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = selected.has(channel.channel_id);
    checkbox.addEventListener('change', () => {
        if (checkbox.checked) selected.add(channel.channel_id); else selected.delete(channel.channel_id);
        row.classList.toggle('selected', checkbox.checked);
    });
    const details = document.createElement('div');
    details.className = 'channel-info';
    const title = document.createElement('div');
    title.className = 'channel-title';
    title.textContent = channel.title;
    const identifier = document.createElement('div');
    identifier.className = 'channel-id';
    identifier.textContent = channel.channel_id;
    details.append(title, identifier);
    row.append(checkbox, details);
    return row;
}

function showEmpty(message) {
    elements.channelList.replaceChildren();
    const state = document.createElement('div');
    state.className = 'empty-state';
    const text = document.createElement('p');
    text.textContent = String(message);
    state.appendChild(text);
    elements.channelList.appendChild(state);
}

async function save() {
    elements.saveBtn.disabled = true;
    elements.saveBtn.textContent = 'Saving...';
    try {
        const response = await fetch(`${API_BASE}/channels/filter-config`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken},
            body: JSON.stringify({
                filter_mode: currentMode,
                allowlist: currentMode === 'allowlist' ? [...selected] : [],
                blocklist: currentMode === 'blocklist' ? [...selected] : []
            })
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error((result.errors || [result.error]).join(', '));
        showStatus('Channel filters saved.', 'success');
    } catch (error) {
        showStatus(`Could not save channel filters: ${error.message}`, 'error');
    } finally {
        elements.saveBtn.disabled = false;
        elements.saveBtn.textContent = 'Save Changes';
    }
}

function showStatus(message, type) {
    elements.statusMessage.textContent = String(message);
    elements.statusMessage.className = `status-message ${type}`;
}

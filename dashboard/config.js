// Configuration Page JavaScript

const API_BASE = window.location.origin;
let csrfToken = null;

async function getCsrfToken() {
    if (csrfToken) return csrfToken;
    const response = await fetch(`${API_BASE}/api/csrf-token`);
    if (!response.ok) throw new Error('Could not initialize request protection');
    const data = await response.json();
    csrfToken = data.csrf_token;
    return csrfToken;
}
async function protectedHeaders() {
    return {
        'Content-Type': 'application/json',
        'X-CSRF-Token': await getCsrfToken()
    };
}

// DOM Elements
const elements = {
    playlistName: document.getElementById('playlistName'),
    playlistVisibility: document.getElementById('playlistVisibility'),
    minDuration: document.getElementById('minDuration'),
    minDurationValue: document.getElementById('minDurationValue'),
    maxDuration: document.getElementById('maxDuration'),
    maxDurationValue: document.getElementById('maxDurationValue'),
    unlimitedDuration: document.getElementById('unlimitedDuration'),
    dateFilterMode: document.getElementById('dateFilterMode'),
    lookbackGroup: document.getElementById('lookbackGroup'),
    daysGroup: document.getElementById('daysGroup'),
    dateRangeGroup: document.getElementById('dateRangeGroup'),
    lookbackHours: document.getElementById('lookbackHours'),
    lookbackHoursValue: document.getElementById('lookbackHoursValue'),
    dateFilterDays: document.getElementById('dateFilterDays'),
    dateFilterStart: document.getElementById('dateFilterStart'),
    dateFilterEnd: document.getElementById('dateFilterEnd'),
    maxVideos: document.getElementById('maxVideos'),
    maxVideosValue: document.getElementById('maxVideosValue'),
    skipLiveContent: document.getElementById('skipLiveContent'),
    ollamaBaseUrl: document.getElementById('ollamaBaseUrl'),
    ollamaModel: document.getElementById('ollamaModel'),
    ollamaTimeout: document.getElementById('ollamaTimeout'),
    sleepMinimumScore: document.getElementById('sleepMinimumScore'),
    sleepQueueSize: document.getElementById('sleepQueueSize'),
    keywordFilterMode: document.getElementById('keywordFilterMode'),
    keywordIncludeGroup: document.getElementById('keywordIncludeGroup'),
    keywordExcludeGroup: document.getElementById('keywordExcludeGroup'),
    keywordAdvancedOptions: document.getElementById('keywordAdvancedOptions'),
    keywordInclude: document.getElementById('keywordInclude'),
    keywordExclude: document.getElementById('keywordExclude'),
    keywordMatchType: document.getElementById('keywordMatchType'),
    keywordCaseSensitive: document.getElementById('keywordCaseSensitive'),
    keywordSearchDescription: document.getElementById('keywordSearchDescription'),
    saveBtn: document.getElementById('saveBtn'),
    previewBtn: document.getElementById('previewBtn'),
    resetBtn: document.getElementById('resetBtn'),
    manageChannelsBtn: document.getElementById('manageChannelsBtn'),
    message: document.getElementById('message'),
    quotaUsed: document.getElementById('quotaUsed'),
    quotaRemaining: document.getElementById('quotaRemaining'),
    quotaBar: document.getElementById('quotaBar'),
    cacheCount: document.getElementById('cacheCount'),
    cacheAge: document.getElementById('cacheAge')
};

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    await getCsrfToken();
    loadConfiguration();
    loadStats();
    setupEventListeners();
});

// Load current configuration
async function loadConfiguration() {
    try {
        const response = await fetch(`${API_BASE}/api/config`);
        const data = await response.json();

        if (data.success) {
            const config = data.config;

            elements.playlistName.value = config.playlist_name || '';
            elements.playlistVisibility.value = config.playlist_visibility || 'unlisted';
            elements.minDuration.value = config.min_duration_seconds || 60;

            // Max duration handling
            if (config.max_duration_seconds) {
                elements.maxDuration.value = config.max_duration_seconds;
                elements.unlimitedDuration.checked = false;
            } else {
                elements.maxDuration.value = 7200; // Set to max
                elements.unlimitedDuration.checked = true;
            }

            // Date filter mode and values
            elements.dateFilterMode.value = config.date_filter_mode || 'lookback';
            elements.lookbackHours.value = config.lookback_hours || 24;
            elements.dateFilterDays.value = config.date_filter_days || 7;
            elements.dateFilterStart.value = config.date_filter_start || '';
            elements.dateFilterEnd.value = config.date_filter_end || '';

            elements.maxVideos.value = config.max_videos || 50;
            elements.skipLiveContent.checked = config.skip_live_content !== false;
            elements.ollamaBaseUrl.value = config.ollama_base_url || 'http://localhost:11434';
            elements.ollamaModel.value = config.ollama_model || 'llama3.2:3b';
            elements.ollamaTimeout.value = config.ollama_timeout_seconds || 30;
            elements.sleepMinimumScore.value = config.sleep_minimum_score ?? 70;
            elements.sleepQueueSize.value = config.sleep_queue_size || 10;

            // Keyword filter settings
            elements.keywordFilterMode.value = config.keyword_filter_mode || 'none';
            elements.keywordInclude.value = (config.keyword_include || []).join('\n');
            elements.keywordExclude.value = (config.keyword_exclude || []).join('\n');
            elements.keywordMatchType.value = config.keyword_match_type || 'any';
            elements.keywordCaseSensitive.checked = config.keyword_case_sensitive || false;
            elements.keywordSearchDescription.checked = config.keyword_search_description || false;

            updateDateFilterVisibility();
            updateKeywordFilterVisibility();
            updateRangeDisplays();
        } else {
            showMessage('Failed to load configuration', 'error');
        }
    } catch (error) {
        console.error('Error loading config:', error);
        showMessage('Error loading configuration. Is the backend running?', 'error');
    }
}

// Load system statistics
async function loadStats() {
    try {
        // Load quota stats
        const quotaResponse = await fetch(`${API_BASE}/api/stats/quota`);
        const quotaData = await quotaResponse.json();

        if (quotaData.success && quotaData.quota) {
            const quota = quotaData.quota;
            elements.quotaUsed.textContent = quota.daily_used.toLocaleString();
            elements.quotaRemaining.textContent = quota.remaining.toLocaleString();

            const percentage = quota.percentage_used;
            elements.quotaBar.style.width = `${percentage}%`;
            elements.quotaBar.textContent = `${percentage.toFixed(1)}%`;

            // Color code the quota bar
            if (percentage > 90) {
                elements.quotaBar.className = 'quota-fill danger';
            } else if (percentage > 70) {
                elements.quotaBar.className = 'quota-fill warning';
            } else {
                elements.quotaBar.className = 'quota-fill';
            }
        }

        // Load cache stats
        const cacheResponse = await fetch(`${API_BASE}/api/stats/cache`);
        const cacheData = await cacheResponse.json();

        if (cacheData.success && cacheData.cache) {
            const cache = cacheData.cache;
            elements.cacheCount.textContent = cache.total_videos.toLocaleString();
            elements.cacheAge.textContent = `${cache.oldest_entry_age_days} days`;
        }
    } catch (error) {
        console.error('Error loading stats:', error);
        // Don't show error message for stats - it's not critical
    }
}

// Setup event listeners
function setupEventListeners() {
    // Range sliders
    elements.minDuration.addEventListener('input', updateRangeDisplays);
    elements.maxDuration.addEventListener('input', updateRangeDisplays);
    elements.lookbackHours.addEventListener('input', updateRangeDisplays);
    elements.maxVideos.addEventListener('input', updateRangeDisplays);

    // Unlimited duration checkbox
    elements.unlimitedDuration.addEventListener('change', () => {
        elements.maxDuration.disabled = elements.unlimitedDuration.checked;
        updateRangeDisplays();
    });

    // Date filter mode dropdown
    elements.dateFilterMode.addEventListener('change', updateDateFilterVisibility);

    // Keyword filter mode dropdown
    elements.keywordFilterMode.addEventListener('change', updateKeywordFilterVisibility);

    // Buttons
    elements.saveBtn.addEventListener('click', saveConfiguration);
    elements.previewBtn.addEventListener('click', previewChanges);
    elements.resetBtn.addEventListener('click', resetToDefaults);
    elements.manageChannelsBtn.addEventListener('click', () => {
        window.location.href = 'channels.html';
    });
}

// Update keyword filter visibility based on selected mode
function updateKeywordFilterVisibility() {
    const mode = elements.keywordFilterMode.value;

    // Hide all groups first
    elements.keywordIncludeGroup.style.display = 'none';
    elements.keywordExcludeGroup.style.display = 'none';
    elements.keywordAdvancedOptions.style.display = 'none';

    // Show appropriate groups based on mode
    if (mode === 'include') {
        elements.keywordIncludeGroup.style.display = 'block';
        elements.keywordAdvancedOptions.style.display = 'block';
    } else if (mode === 'exclude') {
        elements.keywordExcludeGroup.style.display = 'block';
    } else if (mode === 'both') {
        elements.keywordIncludeGroup.style.display = 'block';
        elements.keywordExcludeGroup.style.display = 'block';
        elements.keywordAdvancedOptions.style.display = 'block';
    }
}

// Update date filter visibility based on selected mode
function updateDateFilterVisibility() {
    const mode = elements.dateFilterMode.value;

    // Hide all groups first
    elements.lookbackGroup.style.display = 'none';
    elements.daysGroup.style.display = 'none';
    elements.dateRangeGroup.style.display = 'none';

    // Show the appropriate group
    if (mode === 'lookback') {
        elements.lookbackGroup.style.display = 'block';
    } else if (mode === 'days') {
        elements.daysGroup.style.display = 'block';
    } else if (mode === 'date_range') {
        elements.dateRangeGroup.style.display = 'block';
    }
}

// Update range slider displays
function updateRangeDisplays() {
    // Min duration
    const minDuration = parseInt(elements.minDuration.value);
    const minDurationText = minDuration >= 60
        ? `${Math.floor(minDuration / 60)} min ${minDuration % 60} sec`
        : `${minDuration} seconds`;
    elements.minDurationValue.textContent = minDurationText;

    // Max duration
    if (elements.unlimitedDuration.checked) {
        elements.maxDurationValue.textContent = 'Unlimited';
    } else {
        const maxDuration = parseInt(elements.maxDuration.value);
        const maxDurationText = maxDuration >= 60
            ? `${Math.floor(maxDuration / 60)} min ${maxDuration % 60} sec`
            : `${maxDuration} seconds`;
        elements.maxDurationValue.textContent = maxDurationText;
    }

    // Lookback hours
    const lookbackHours = parseInt(elements.lookbackHours.value);
    const lookbackText = lookbackHours >= 24
        ? `${Math.floor(lookbackHours / 24)} days`
        : `${lookbackHours} hours`;
    elements.lookbackHoursValue.textContent = lookbackText;

    // Max videos
    const maxVideos = parseInt(elements.maxVideos.value);
    elements.maxVideosValue.textContent = `${maxVideos} videos`;
}

// Get current form values as config object
function getConfigFromForm() {
    const config = {
        playlist_name: elements.playlistName.value,
        playlist_visibility: elements.playlistVisibility.value,
        min_duration_seconds: parseInt(elements.minDuration.value),
        lookback_hours: parseInt(elements.lookbackHours.value),
        max_videos: parseInt(elements.maxVideos.value),
        skip_live_content: elements.skipLiveContent.checked,
        ollama_base_url: elements.ollamaBaseUrl.value.trim(),
        ollama_model: elements.ollamaModel.value.trim(),
        ollama_timeout_seconds: parseInt(elements.ollamaTimeout.value),
        sleep_minimum_score: parseFloat(elements.sleepMinimumScore.value),
        sleep_queue_size: parseInt(elements.sleepQueueSize.value)
    };

    // Only include max_duration_seconds if not unlimited
    if (!elements.unlimitedDuration.checked) {
        config.max_duration_seconds = parseInt(elements.maxDuration.value);
    } else {
        config.max_duration_seconds = null;
    }

    // Date filter settings
    const dateMode = elements.dateFilterMode.value;
    config.date_filter_mode = dateMode;

    if (dateMode === 'days') {
        config.date_filter_days = parseInt(elements.dateFilterDays.value);
        config.date_filter_start = null;
        config.date_filter_end = null;
    } else if (dateMode === 'date_range') {
        config.date_filter_days = null;
        config.date_filter_start = elements.dateFilterStart.value || null;
        config.date_filter_end = elements.dateFilterEnd.value || null;
    } else {
        // lookback mode
        config.date_filter_days = null;
        config.date_filter_start = null;
        config.date_filter_end = null;
    }

    // Keyword filter settings
    const keywordMode = elements.keywordFilterMode.value;
    config.keyword_filter_mode = keywordMode;

    // Parse textarea values (one keyword per line)
    const includeText = elements.keywordInclude.value.trim();
    const excludeText = elements.keywordExclude.value.trim();

    config.keyword_include = includeText ? includeText.split('\n').map(k => k.trim()).filter(k => k) : null;
    config.keyword_exclude = excludeText ? excludeText.split('\n').map(k => k.trim()).filter(k => k) : null;
    config.keyword_match_type = elements.keywordMatchType.value;
    config.keyword_case_sensitive = elements.keywordCaseSensitive.checked;
    config.keyword_search_description = elements.keywordSearchDescription.checked;

    return config;
}

// Save configuration
async function saveConfiguration() {
    try {
        setLoading(true);
        const config = getConfigFromForm();

        const response = await fetch(`${API_BASE}/api/config`, {
            method: 'PUT',
            headers: await protectedHeaders(),
            body: JSON.stringify(config)
        });

        const data = await response.json();

        if (data.success) {
            showMessage('✅ Configuration saved successfully!', 'success');
            setTimeout(() => hideMessage(), 3000);
        } else {
            const errors = data.errors ? data.errors.join(', ') : 'Unknown error';
            showMessage(`❌ Failed to save: ${errors}`, 'error');
        }
    } catch (error) {
        console.error('Error saving config:', error);
        showMessage('❌ Error saving configuration', 'error');
    } finally {
        setLoading(false);
    }
}

// Preview changes (dry run)
async function previewChanges() {
    try {
        setLoading(true);
        const config = getConfigFromForm();

        showMessage('🔍 Running preview with new settings... This may take a few minutes.', 'success');

        // First validate the config
        const validateResponse = await fetch(`${API_BASE}/api/config/validate`, {
            method: 'POST',
            headers: await protectedHeaders(),
            body: JSON.stringify(config)
        });

        const validateData = await validateResponse.json();

        if (!validateData.valid) {
            const errors = validateData.errors.join(', ');
            showMessage(`❌ Invalid configuration: ${errors}`, 'error');
            return;
        }

        const response = await fetch(`${API_BASE}/api/refresh`, {
            method: 'POST',
            headers: await protectedHeaders(),
            body: JSON.stringify({dry_run: true})
        });
        const result = await response.json();
        if (response.status !== 202 || !result.success) {
            throw new Error(result.error || 'Could not start preview');
        }
        showMessage(`Preview started. Job ID: ${result.job_id}`, 'success');

    } catch (error) {
        console.error('Error previewing:', error);
        showMessage('❌ Error running preview', 'error');
    } finally {
        setLoading(false);
    }
}

// Reset to defaults
async function resetToDefaults() {
    if (!confirm('Are you sure you want to reset all settings to defaults?')) {
        return;
    }

    try {
        setLoading(true);

        const response = await fetch(`${API_BASE}/api/config/reset`, {
            method: 'POST',
            headers: await protectedHeaders(),
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (data.success) {
            showMessage('✅ Configuration reset to defaults', 'success');
            // Reload the configuration
            await loadConfiguration();
            setTimeout(() => hideMessage(), 3000);
        } else {
            showMessage('❌ Failed to reset configuration', 'error');
        }
    } catch (error) {
        console.error('Error resetting config:', error);
        showMessage('❌ Error resetting configuration', 'error');
    } finally {
        setLoading(false);
    }
}

// Show message
function showMessage(text, type) {
    elements.message.textContent = text;
    elements.message.className = `message ${type} show`;
}

// Hide message
function hideMessage() {
    elements.message.className = 'message';
}

// Set loading state
function setLoading(isLoading) {
    const container = document.querySelector('.config-container');
    if (isLoading) {
        container.classList.add('loading');
    } else {
        container.classList.remove('loading');
    }
}

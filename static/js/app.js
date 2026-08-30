let investigationData = null;

function showToast(message) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('cv-upload');
const uploadSuccess = document.getElementById('upload-success');
const uploadPrompt = document.getElementById('upload-prompt');
const filenameDisplay = document.getElementById('filename-display');
let fileUploaded = false;

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
});

dropZone.addEventListener('drop', handleDrop, false);
fileInput.addEventListener('change', handleFiles, false);

function handleDrop(e) {
    handleFiles({ target: { files: e.dataTransfer.files } });
}

function handleFiles(e) {
    const files = e.target.files;
    if (files.length > 0) {
        const file = files[0];
        if (file.type === 'application/pdf') {
            filenameDisplay.textContent = `${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`;
            uploadSuccess.classList.remove('hidden');
            uploadPrompt.classList.add('hidden');
            fileUploaded = true;
        } else {
            showToast('Please upload a PDF file.');
        }
    }
}

function resetUpload(e) {
    e.preventDefault();
    e.stopPropagation();
    fileInput.value = '';
    uploadSuccess.classList.add('hidden');
    uploadPrompt.classList.remove('hidden');
    fileUploaded = false;
}

const jdTextarea = document.getElementById('job-description');
const charCountDisplay = document.getElementById('char-count');

jdTextarea.addEventListener('input', function() {
    charCountDisplay.textContent = `${this.value.length} / 2000`;
});

const stateInput = document.getElementById('state-input');
const stateProgress = document.getElementById('state-progress');
const stateResults = document.getElementById('state-results');

function startInvestigation() {
    const jd = jdTextarea.value;
    if (!fileUploaded) {
        showToast('Please upload a CV.');
        return;
    }
    if (jd.trim() === '') {
        showToast('Please provide a job description.');
        return;
    }

    const formData = new FormData();
    formData.append('cv_file', fileInput.files[0]);
    formData.append('job_description', jd);

    resetSteps();
    transitionState(stateInput, stateProgress);
    appendLog('[SYSTEM] Uploading CV and job description...');

    fetch('/process-cv/', {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
        },
    })
    .then(async (response) => {
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Request failed');
        }
        return data.data;
    })
    .then((data) => {
        investigationData = data;
        runAgentProgress(data);
    })
    .catch((error) => {
        appendLog(`[ERROR] ${error.message}`);
        showToast(`Error: ${error.message}`);
        setTimeout(() => transitionState(stateProgress, stateInput), 800);
    });
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function resetApp() {
    const visible = [stateInput, stateProgress, stateResults].find(
        (el) => el.style.display !== 'none'
    );
    if (visible && visible !== stateInput) {
        transitionState(visible, stateInput);
    }
    resetUpload(new Event('click'));
    jdTextarea.value = '';
    charCountDisplay.textContent = '0 / 2000';
    resetSteps();
    investigationData = null;
    document.getElementById('activity-feed').innerHTML = '';
}

function transitionState(hideElem, showElem) {
    hideElem.classList.remove('fade-in');
    hideElem.classList.add('fade-out');

    setTimeout(() => {
        hideElem.style.display = 'none';
        hideElem.classList.remove('fade-out');

        showElem.style.display = 'block';
        showElem.classList.add('fade-in');

        showElem.querySelectorAll('.stagger-1, .stagger-2, .stagger-3').forEach((el) => {
            el.style.animation = 'none';
            el.offsetHeight;
            el.style.animation = null;
        });
    }, 300);
}

function appendLog(message, options = {}) {
    const feed = document.getElementById('activity-feed');
    const entry = document.createElement('div');
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;

    if (options.highlight) {
        entry.classList.add('text-primary', 'pl-md');
    }
    if (options.warn) {
        entry.style.color = '#92400e';
    }

    feed.appendChild(entry);
    feed.scrollTop = feed.scrollHeight;
}

function runAgentProgress(data) {
    const { extraction, analysis } = data;
    const filename = fileInput.files[0]?.name || 'CV document';

    document.getElementById('progress-subtitle').textContent = filename;

    const logs = [
        `[PARSE] PDF extracted. ${extraction.page_count} page(s), ${extraction.text.length} characters.`,
        `[PARSE] Found ${extraction.urls.length} URL(s) in PDF.`,
        `[GEMINI] Extracted ${analysis.requirements.length} requirement(s) from job description.`,
        ...analysis.requirements.map(
            (req) => `-> ${req.name} (${req.importance}): ${req.description}`
        ),
        `[GEMINI] Identified ${analysis.claims.length} claim(s) supported by the CV.`,
        ...analysis.claims.map(
            (claim) => `-> ${claim.requirement}: ${claim.claim}`
        ),
        `[GEMINI] Collected ${analysis.urls.length} public URL(s) for verification.`,
        '[SYSTEM] Extraction complete. Verification will run in a later step.',
    ];

    let logIndex = 0;
    updateStep(0, 1);

    const logInterval = setInterval(() => {
        if (logIndex < logs.length) {
            const line = logs[logIndex];
            appendLog(line, {
                highlight: line.startsWith('->'),
            });

            if (logIndex === 0) updateStep(1, 2);
            if (logIndex === 2) updateStep(2, 3);

            logIndex++;
        } else {
            clearInterval(logInterval);
            setTimeout(() => {
                renderResults(data);
                transitionState(stateProgress, stateResults);
            }, 400);
        }
    }, 250);
}

function renderResults(data) {
    const { extraction, analysis } = data;
    const filename = fileInput.files[0]?.name || 'CV document';

    document.getElementById('results-subtitle').textContent =
        `${filename} • ${extraction.page_count} page(s) • Analyzed just now`;

    document.getElementById('stat-requirements').textContent = analysis.requirements.length;
    document.getElementById('stat-claims').textContent = analysis.claims.length;
    document.getElementById('stat-urls').textContent = analysis.urls.length;

    const urlsList = document.getElementById('urls-list');
    urlsList.innerHTML = '';

    if (analysis.urls.length === 0) {
        urlsList.innerHTML = '<li class="text-on-surface-variant">No URLs found.</li>';
    } else {
        analysis.urls.forEach((url) => {
            const li = document.createElement('li');
            const link = document.createElement('a');
            link.href = url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.className = 'text-primary underline hover:text-primary-container';
            link.textContent = url;
            li.appendChild(link);
            urlsList.appendChild(li);
        });
    }

    const claimsList = document.getElementById('claims-list');
    claimsList.innerHTML = '';

    if (analysis.claims.length === 0) {
        claimsList.innerHTML =
            '<p class="p-md font-body-md text-body-md text-on-surface-variant">No claims matched to requirements.</p>';
        return;
    }

    const importanceByRequirement = Object.fromEntries(
        analysis.requirements.map((req) => [req.name, req.importance])
    );

    analysis.claims.forEach((claim) => {
        const importance = importanceByRequirement[claim.requirement] || 'medium';
        const row = document.createElement('div');
        row.className = 'border-b border-surface-variant last:border-b-0 hover:bg-[#F8FAFC] transition-colors';
        row.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-12 gap-md p-md items-center cursor-pointer accordion-trigger" onclick="toggleAccordion(this)">
                <div class="col-span-3 font-body-md text-body-md text-on-surface font-medium flex items-center gap-sm">
                    <span class="material-symbols-outlined text-[16px] accordion-icon text-on-surface-variant">expand_more</span>
                    ${escapeHtml(claim.requirement)}
                </div>
                <div class="col-span-5 font-body-md text-body-md text-on-surface-variant truncate">
                    ${escapeHtml(claim.claim)}
                </div>
                <div class="col-span-2 font-label-sm text-label-sm text-on-surface-variant capitalize">
                    ${escapeHtml(importance)}
                </div>
                <div class="col-span-2 flex justify-start md:justify-end">
                    <span class="inline-flex items-center gap-xs px-[8px] py-[4px] rounded-DEFAULT font-label-sm text-label-sm" style="background-color: rgba(100, 94, 251, 0.1); color: #3730a3;">
                        <span class="material-symbols-outlined text-[14px]">pending</span> Pending verification
                    </span>
                </div>
            </div>
            <div class="accordion-content bg-surface p-md border-t border-surface-variant">
                <div class="pl-xl">
                    <h4 class="font-label-sm text-label-sm text-on-surface-variant uppercase mb-xs">CV Source</h4>
                    <p class="font-body-md text-body-md text-on-surface">${escapeHtml(claim.source_from_cv)}</p>
                </div>
            </div>
        `;
        claimsList.appendChild(row);
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function updateStep(current, next) {
    if (current >= 1 && current <= 3) {
        const currentDot = document.getElementById(`step${current}-dot`);
        const currentText = document.getElementById(`step${current}-text`);
        if (currentDot) {
            currentDot.classList.remove('active');
            currentDot.classList.add('completed');
            currentText.classList.remove('text-on-surface');
            currentText.classList.add('text-on-surface-variant');
        }
    }
    if (next >= 1 && next <= 3) {
        const nextDot = document.getElementById(`step${next}-dot`);
        const nextText = document.getElementById(`step${next}-text`);
        if (nextDot) {
            nextDot.classList.add('active');
            nextText.classList.remove('text-on-surface-variant');
            nextText.classList.add('text-on-surface');
        }
    }
}

function resetSteps() {
    for (let i = 1; i <= 3; i++) {
        const dot = document.getElementById(`step${i}-dot`);
        const text = document.getElementById(`step${i}-text`);
        if (dot) {
            dot.className = 'progress-dot';
            text.className = 'font-body-md text-body-md text-on-surface-variant';
        }
    }
    document.getElementById('step1-dot').classList.add('active');
    document.getElementById('step1-text').classList.replace('text-on-surface-variant', 'text-on-surface');
    document.getElementById('activity-feed').innerHTML = '';
    document.getElementById('progress-subtitle').textContent = 'Processing uploaded document...';
}

function toggleAccordion(element) {
    const row = element.parentElement;
    const content = row.querySelector('.accordion-content');
    const isOpen = content.classList.contains('open');

    if (!isOpen) {
        content.classList.add('open');
        element.classList.add('open');
    } else {
        content.classList.remove('open');
        element.classList.remove('open');
    }
}

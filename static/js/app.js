let investigationData = null;
let claimsData = [];

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
        claimsData = data.claims || [];
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
    const { extraction, requirements, claims, sources } = data;
    const filename = fileInput.files[0]?.name || 'CV document';

    document.getElementById('progress-subtitle').textContent = filename;

    const logs = [
        `[PARSE] PDF extracted. ${extraction.page_count} page(s), ${extraction.urls.length} URL(s) found.`,
        `[GEMINI] Structuring analysis complete.`,
        `[GEMINI] Extracted ${requirements.length} requirement(s) from job description.`,
        ...requirements.map(
            (req) => `-> ${req.name}: ${req.importance} priority`
        ),
        `[GEMINI] Identified ${claims.length} candidate claim(s) matching requirements.`,
        ...claims.map(
            (claim) => `-> ${claim.requirement}: ${claim.claim.substring(0, 50)}...`
        ),
        `[GEMINI] Found ${sources.length} public source(s) for verification.`,
        ...sources.map(
            (source) => `-> ${source.source_type}: ${source.url}`
        ),
        `[SYSTEM] Stage 2 complete. Database populated with structured information.`,
    ];

    logs.push('[SYSTEM] Ready for verification stage (Stages 4-8).');

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
    const { extraction, requirements, claims, sources, investigation_id } = data;
    const filename = fileInput.files[0]?.name || 'CV document';

    document.getElementById('results-subtitle').textContent =
        `${filename} • ${extraction.page_count} page(s) • Structured just now`;

    document.getElementById('stat-requirements').textContent = requirements.length;
    
    // For Stage 2, we show claims count instead of met/partial since verification hasn't happened yet
    document.getElementById('stat-met').textContent = claims.length;
    document.getElementById('stat-partial').textContent = sources.length;

    // Show verify all button if we have claims and sources
    const verifyAllBtn = document.getElementById('verify-all-btn');
    if (claims.length > 0 && sources.length > 0 && investigation_id) {
        verifyAllBtn.style.display = 'flex';
    } else {
        verifyAllBtn.style.display = 'none';
    }

    const requirementsList = document.getElementById('requirements-list');
    requirementsList.innerHTML = '';

    if (requirements.length === 0) {
        requirementsList.innerHTML =
            '<p class="p-md font-body-md text-body-md text-on-surface-variant">No requirements extracted yet.</p>';
        return;
    }

    requirements.forEach((requirement) => {
        const requirementClaims = claims.filter(c => c.requirement === requirement.name);
        
        const row = document.createElement('div');
        row.className = 'border-b border-surface-variant last:border-b-0 hover:bg-[#F8FAFC] transition-colors';
        row.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-12 gap-md p-md items-center cursor-pointer accordion-trigger" onclick="toggleAccordion(this)">
                <div class="col-span-4 font-body-md text-body-md text-on-surface font-medium flex items-center gap-sm">
                    <span class="material-symbols-outlined text-[16px] accordion-icon text-on-surface-variant">expand_more</span>
                    ${escapeHtml(requirement.name)}
                </div>
                <div class="col-span-4 font-body-md text-body-md text-on-surface-variant truncate">
                    ${requirementClaims.length > 0 ? escapeHtml(requirementClaims[0].claim.substring(0, 80)) + '...' : 'No claims identified'}
                </div>
                <div class="col-span-2 font-label-sm text-label-sm text-on-surface-variant">
                    ${requirement.importance}
                </div>
                <div class="col-span-2 flex justify-start md:justify-end">
                    <span class="inline-flex items-center gap-xs px-[8px] py-[4px] rounded-DEFAULT font-label-sm text-label-sm status-badge" style="background-color: #6366f120; color: #6366f1;">
                        <span class="material-symbols-outlined text-[14px]">pending</span> Ready
                    </span>
                </div>
            </div>
            <div class="accordion-content bg-surface p-md border-t border-surface-variant">
                <div class="pl-xl">
                    <h4 class="font-label-sm text-label-sm text-on-surface-variant uppercase mb-xs">Description</h4>
                    <p class="font-body-md text-body-md text-on-surface mb-md">${escapeHtml(requirement.description || 'No description provided')}</p>
                    
                    <h4 class="font-label-sm text-label-sm text-on-surface-variant uppercase mb-xs">Importance</h4>
                    <p class="font-body-md text-body-md text-on-surface mb-md">${escapeHtml(requirement.importance)}</p>
                    
                    ${requirementClaims.length > 0 ? `
                        <h4 class="font-label-sm text-label-sm text-on-surface-variant uppercase mb-xs">Candidate Claims (${requirementClaims.length})</h4>
                        ${requirementClaims.map(claim => `
                            <div class="mb-md p-sm bg-surface-container-lowest rounded border border-surface-variant" data-claim-id="${claim.id}">
                                <div class="flex items-center justify-between mb-xs">
                                    <div class="flex items-center gap-xs">
                                        <span class="material-symbols-outlined text-[14px] text-primary">person</span>
                                        <span class="font-label-sm text-label-sm text-on-surface">Claim from CV</span>
                                    </div>
                                    <button class="verify-btn btn-ghost text-xs px-xs py-xs rounded border border-surface-variant hover:bg-surface-container-low" onclick="event.stopPropagation(); verifyClaim(${claim.id}, this.closest('[data-claim-id]'))">
                                        <span class="material-symbols-outlined text-[14px]">verified</span> Verify
                                    </button>
                                </div>
                                <p class="font-body-sm text-body-sm text-on-surface">${escapeHtml(claim.claim)}</p>
                                ${claim.source_from_cv ? `
                                    <div class="mt-xs pt-xs border-t border-surface-variant">
                                        <span class="font-label-xs text-label-xs text-on-surface-variant">CV Source: ${escapeHtml(claim.source_from_cv.substring(0, 100))}...</span>
                                    </div>
                                ` : ''}
                                <div class="evidence-details"></div>
                            </div>
                        `).join('')}
                    ` : '<p class="font-body-sm text-body-sm text-on-surface-variant">No claims identified for this requirement.</p>'}
                    
                    <div class="mt-md pt-md border-t border-surface-variant">
                        <h4 class="font-label-sm text-label-sm text-on-surface-variant uppercase mb-xs">Available Sources for Verification</h4>
                        <div class="flex flex-wrap gap-xs">
                            ${sources.map(source => `
                                <span class="inline-flex items-center gap-xs px-xs py-xs bg-surface-container-lowest rounded border border-surface-variant">
                                    <span class="material-symbols-outlined text-[12px] text-on-surface-variant">${source.source_type === 'github' ? 'code' : source.source_type === 'portfolio' ? 'work' : 'language'}</span>
                                    <span class="font-label-xs text-label-xs text-on-surface-variant">${source.source_type}</span>
                                </span>
                            `).join('')}
                        </div>
                    </div>
                </div>
            </div>
        `;
        requirementsList.appendChild(row);
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
    document.getElementById('step1-text').classList.remove('text-on-surface-variant');
    document.getElementById('step1-text').classList.add('text-on-surface');
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

function verifyClaim(claimId, claimElement) {
    const verifyBtn = claimElement.querySelector('.verify-btn');
    if (verifyBtn) {
        verifyBtn.disabled = true;
        verifyBtn.innerHTML = '<span class="material-symbols-outlined text-[14px] animate-spin">refresh</span> Verifying...';
    }

    const formData = new FormData();
    formData.append('claim_id', claimId);

    fetch('/verify-claim/', {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
        },
    })
    .then(async (response) => {
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Verification failed');
        }
        return data.data;
    })
    .then((result) => {
        showToast(`Claim verification complete: ${result.status}`);
        updateClaimStatus(claimElement, result);
        
        // Update the claim in our data
        const claimIndex = claimsData.findIndex(c => c.id === claimId);
        if (claimIndex !== -1) {
            claimsData[claimIndex].verification_status = result.status;
            claimsData[claimIndex].verification_result = result;
        }
    })
    .catch((error) => {
        showToast(`Verification error: ${error.message}`);
        if (verifyBtn) {
            verifyBtn.disabled = false;
            verifyBtn.innerHTML = '<span class="material-symbols-outlined text-[14px]">verified</span> Verify';
        }
    });
}

function verifyAllClaims() {
    if (!investigationData || !investigationData.investigation_id) {
        showToast('No investigation data available');
        return;
    }

    const verifyAllBtn = document.getElementById('verify-all-btn');
    verifyAllBtn.disabled = true;
    verifyAllBtn.innerHTML = '<span class="material-symbols-outlined text-[18px] animate-spin">refresh</span> Verifying All...';

    const formData = new FormData();
    formData.append('investigation_id', investigationData.investigation_id);

    fetch('/verify-all-claims/', {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
        },
    })
    .then(async (response) => {
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Bulk verification failed');
        }
        return data.data;
    })
    .then((result) => {
        showToast(`Verification complete: ${result.verified} verified, ${result.unverified} unverified`);
        
        // Update all claim statuses in the UI
        result.results.forEach(claimResult => {
            const claimElement = document.querySelector(`[data-claim-id="${claimResult.claim_id}"]`);
            if (claimElement) {
                updateClaimStatus(claimElement, claimResult);
            }
        });

        // Update investigation status
        investigationData.verification_complete = true;
        investigationData.verification_results = result;
        
        // Hide the verify all button
        verifyAllBtn.style.display = 'none';
    })
    .catch((error) => {
        showToast(`Bulk verification error: ${error.message}`);
        verifyAllBtn.disabled = false;
        verifyAllBtn.innerHTML = '<span class="material-symbols-outlined text-[18px]">verified</span> Verify All Claims';
    });
}

function updateClaimStatus(claimElement, result) {
    const statusBadge = claimElement.querySelector('.status-badge');
    const verifyBtn = claimElement.querySelector('.verify-btn');
    
    if (statusBadge) {
        const statusColor = result.status === 'verified' ? '#059669' : result.status === 'unverified' ? '#dc2626' : '#6366f1';
        const statusIcon = result.status === 'verified' ? 'check_circle' : result.status === 'unverified' ? 'cancel' : 'help';
        
        statusBadge.style.backgroundColor = `${statusColor}20`;
        statusBadge.style.color = statusColor;
        statusBadge.innerHTML = `<span class="material-symbols-outlined text-[14px]">${statusIcon}</span> ${result.status.charAt(0).toUpperCase() + result.status.slice(1)}`;
    }
    
    if (verifyBtn) {
        verifyBtn.style.display = 'none';
    }
    
    // Add evidence details if available
    const evidenceSection = claimElement.querySelector('.evidence-details');
    if (evidenceSection && result.evaluation) {
        evidenceSection.innerHTML = `
            <div class="mt-md pt-md border-t border-surface-variant">
                <h4 class="font-label-sm text-label-sm text-on-surface-variant uppercase mb-xs">Verification Evidence</h4>
                <p class="font-body-sm text-body-sm text-on-surface mb-sm">${escapeHtml(result.evaluation.finding || 'No finding available')}</p>
                <div class="flex gap-xs">
                    <span class="inline-flex items-center gap-xs px-xs py-xs bg-surface-container-lowest rounded border border-surface-variant">
                        <span class="font-label-xs text-label-xs text-on-surface-variant">Strength: ${result.evaluation.evidence_strength || 'N/A'}</span>
                    </span>
                    <span class="inline-flex items-center gap-xs px-xs py-xs bg-surface-container-lowest rounded border border-surface-variant">
                        <span class="font-label-xs text-label-xs text-on-surface-variant">Sources: ${result.evaluation.details?.sources_checked || 0}</span>
                    </span>
                </div>
            </div>
        `;
    }
}

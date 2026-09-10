// Global variables
let draggedChartId = null;
let selectedChart = null;
let selectedCharts = [];  // 여러 차트 선택을 위한 배열
let charts = [];
let parameters = [];
let updateTimeout = null;  // 디바운스를 위한 타임아웃 변수
let fftChart = null;  // FFT 차트 인스턴스
let scatterChart = null;  // Scatter 차트 인스턴스
let isRestoringLayout = false; // 차트 레이아웃 복원 중인지 여부 플래그
let isFixedScale = false; // Fixed Scale 토글 상태
let isShowDescription = false; // Show Description 토글 상태
let lineAlphaPercent = 0; // 라인 투명도 (% 0~100)
let gridStack = null; // GridStack instance
let isCanvasMode = false; // Canvas mode state
let alignmentPolicy = localStorage.getItem('wavelab-alignment-policy') || 'linear';

async function runBackgroundJob(kind, payload) {
    const status = document.getElementById('job-status');
    const indicator = document.getElementById('data-state-indicator');
    indicator?.classList.remove('idle', 'ready');
    indicator?.classList.add('busy');
    const created = await fetch(`/api/jobs/${encodeURIComponent(kind)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const initial = await created.json();
    if (!created.ok) throw new Error(initial.error || 'Failed to create analysis job');
    if (status) status.textContent = `${kind.toUpperCase()} · QUEUED`;
    while (true) {
        await new Promise(resolve => setTimeout(resolve, 300));
        const response = await fetch(`/api/jobs/${initial.id}`);
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || 'Failed to read job state');
        if (status) status.textContent = `${kind.toUpperCase()} · ${job.progress}%`;
        if (job.state === 'completed') {
            indicator?.classList.remove('busy', 'idle');
            indicator?.classList.add('ready');
            if (status) {
                status.textContent = `${kind.toUpperCase()} · DONE`;
                setTimeout(() => {
                    if (status.textContent === `${kind.toUpperCase()} · DONE`) status.textContent = 'READY';
                }, 2500);
            }
            return job.result;
        }
        if (job.state === 'failed' || job.state === 'cancelled') {
            indicator?.classList.remove('busy', 'idle');
            indicator?.classList.add('ready');
            if (status) status.textContent = `${kind.toUpperCase()} · ${job.state.toUpperCase()}`;
            throw new Error(job.error || `Job ${job.state}`);
        }
    }
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[char]);
}

async function showChannelQuality() {
    const response = await fetch('/api/channel_quality');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Failed to load channel quality');
    const channels = data.channels || [];
    const total = channels.reduce((sum, item) => sum + (item.count || 0), 0);
    const missing = channels.reduce((sum, item) => sum + (item.missing_count || 0), 0);
    const duplicates = channels.reduce((sum, item) => sum + (item.duplicate_count || 0), 0);
    document.getElementById('quality-summary').textContent =
        `${channels.length.toLocaleString()} channels · ${total.toLocaleString()} stored samples · ${missing.toLocaleString()} missing · ${duplicates.toLocaleString()} duplicates removed`;
    document.getElementById('quality-table-body').innerHTML = channels.map(item => `<tr>
        <td>${escapeHtml(item.parameter)}</td>
        <td>${Number(item.count || 0).toLocaleString()}</td>
        <td>${Number.isFinite(item.sampling_rate) ? item.sampling_rate.toFixed(3) : '—'}</td>
        <td>${Number(item.missing_count || 0).toLocaleString()}</td>
        <td>${Number(item.duplicate_count || 0).toLocaleString()}</td>
        <td>${Number.isFinite(item.start) ? item.start.toFixed(6) : '—'}</td>
        <td>${Number.isFinite(item.end) ? item.end.toFixed(6) : '—'}</td>
    </tr>`).join('');
    document.getElementById('quality-popup').style.display = 'flex';
}

// 기본 라인 색상 (파라미터 시리즈용)
const baseSeriesColors = ['#2196F3', '#FF5722', '#4CAF50'];

function hexToRgba(hex, alpha) {
    const sanitized = hex.replace('#', '');
    const bigint = parseInt(sanitized, 16);
    const r = (bigint >> 16) & 255;
    const g = (bigint >> 8) & 255;
    const b = bigint & 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function applyLineTransparencyToAllCharts() {
    const input = document.getElementById('line-alpha-input');
    let percent = lineAlphaPercent;
    if (input) {
        const val = parseFloat(input.value);
        if (!isNaN(val)) percent = Math.min(100, Math.max(0, val));
    }
    lineAlphaPercent = percent;
    const alpha = 1 - (percent / 100);
    charts.forEach(chart => {
        if (!chart.plot || !chart.plot.series) return;
        for (let i = 1; i < chart.plot.series.length; i++) {
            const seriesDef = chart.plot.series[i];
            if (!seriesDef) continue;
            seriesDef.alpha = alpha;
            if (typeof chart.plot.setSeries === 'function') {
                chart.plot.setSeries(i, { alpha });
            }
        }
        // 강제 리렌더
        if (typeof chart.plot.redraw === 'function') {
            chart.plot.redraw(false, false);
        } else if (typeof chart.plot.setData === 'function' && chart.plot.data) {
            chart.plot.setData(chart.plot.data);
        }
    });
}

// 전역에서 사용할 수 있도록 arrayMin/arrayMax 함수 정의
function arrayMin(arr) {
    if (!arr || arr.length === 0) return NaN;
    return arr.reduce((min, v) => v < min ? v : min, arr[0]);
}
function arrayMax(arr) {
    if (!arr || arr.length === 0) return NaN;
    return arr.reduce((max, v) => v > max ? v : max, arr[0]);
}

// 대용량 시계열 다운샘플링 (버킷 min/max) 및 점진 렌더링 유틸
function getChartPixelWidth(uPlotInstance) {
    try {
        const w = uPlotInstance?.root?.getBoundingClientRect?.().width;
        return (w && isFinite(w)) ? Math.floor(w) : 800;
    } catch (_) {
        return 800;
    }
}



// DOM Elements
const fileInput = document.getElementById('file-input');
const uploadBtn = document.getElementById('upload-btn');
const uploadFixedWingBtn = document.getElementById('upload-fixed-wing-btn');
const uploadStatus = document.getElementById('upload-status');
const addChartBtn = document.getElementById('addChartBtn');
const scaleBtn = document.getElementById('scaleBtn');
const minmaxBtn = document.getElementById('minMaxBtn');
const fftBtn = document.getElementById('fft-btn');
const scatterBtn = document.getElementById('scatter-btn');
const plotArea = document.getElementById('plot-area');
const parametersList = document.getElementById('parameters-list');
const minmaxPopup = document.getElementById('minmax-popup');
const minmaxInfoText = document.getElementById('minmax-info-text');
const fftPopup = document.getElementById('fft-popup');
const fftChartElement = document.getElementById('fft-chart');
const scatterPopup = document.getElementById('scatter-popup');
const scatterChartElement = document.getElementById('scatter-chart');
const parameterSearchInput = document.getElementById('parameter-search-input');
const clearParameterSearchBtn = document.getElementById('clear-parameter-search');

function setDatasetStatus(fileName, state = 'ready') {
    const fileLabel = document.getElementById('status-file-name');
    const indicator = document.getElementById('data-state-indicator');
    if (fileLabel) {
        fileLabel.textContent = fileName || 'NO DATASET';
        fileLabel.title = fileName || '';
    }
    if (indicator) {
        indicator.classList.remove('idle', 'ready', 'busy');
        indicator.classList.add(state);
    }
}

function updateParameterResultCount(visible, total) {
    const count = document.getElementById('parameter-result-count');
    const statusCount = document.getElementById('status-channel-count');
    if (count) count.textContent = visible === total ? `${total}` : `${visible} / ${total}`;
    if (statusCount) statusCount.textContent = `${total.toLocaleString()} CH`;
}

function applyParameterFilter() {
    const query = (parameterSearchInput?.value || '').trim().toLocaleLowerCase();
    const items = Array.from(parametersList.querySelectorAll('.parameter-item'));
    let visible = 0;
    items.forEach(item => {
        const matches = !query || (item.dataset.search || '').includes(query);
        item.hidden = !matches;
        if (matches) visible += 1;
    });
    parametersList.querySelector('.parameter-empty-state')?.remove();
    if (items.length && visible === 0) {
        parametersList.insertAdjacentHTML('beforeend',
            '<div class="parameter-empty-state">No channels match this search.</div>');
    }
    updateParameterResultCount(visible, items.length);
}

parameterSearchInput?.addEventListener('input', applyParameterFilter);
clearParameterSearchBtn?.addEventListener('click', () => {
    parameterSearchInput.value = '';
    applyParameterFilter();
    parameterSearchInput.focus();
});

// Filter button and dropdown handling
const filterBtn = document.getElementById('filter-btn');
const filterPopup = document.getElementById('filter-popup');
const filterInfoPopup = document.getElementById('filter-info-popup');
const filterInfoText = document.getElementById('filter-info-text');

let currentFilterType = null;

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
        
        tab.classList.add('active');
        document.getElementById(`${tab.dataset.tab}-tab`).classList.add('active');

        const plotArea = document.getElementById('plot-area');
        const notepadArea = document.getElementById('notepad-area');

        if (tab.dataset.tab === 'plot') {
            notepadArea.style.display = 'none';
            const canvasArea = document.getElementById('canvas-area');
            if (isCanvasMode) {
                plotArea.style.display = 'none';
                if (canvasArea) canvasArea.style.display = 'block';
            } else {
                plotArea.style.display = 'grid';
                if (canvasArea) canvasArea.style.display = 'none';
            }
            
            loadParameters();
            
            if (charts.length === 0 && !isRestoringLayout) {
                for (let i = 0; i < INITIAL_CHARTS; i++) {
                    createChart();
                }
                updateGridLayout();
            }
        } else if (tab.dataset.tab === 'file') {
            plotArea.style.display = 'none';
            notepadArea.style.display = 'flex';
        }
    });
});

// File upload handling
uploadBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
        uploadStatus.textContent = 'Uploading File....';
        uploadStatus.className = 'uploading';
        
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (response.ok) {
            // 어떤 파일을 올리든, 성공 시 플롯 영역을 완전히 초기화
            resetPlotArea();

            uploadStatus.className = 'success';
            
            // 업로드된 파일명 표시
            const currentFileDiv = document.getElementById('current-file');
            currentFileDiv.innerHTML = `<strong>Current File:</strong><br>${escapeHtml(file.name)}`;
            currentFileDiv.style.display = 'block';
            setDatasetStatus(file.name);
            
            const fileExt = file.name.toLowerCase().split('.').pop();
            
            if (fileExt === 'db') {
                uploadStatus.textContent = 'Database loaded successfully!';
                loadSessionNotes(); // 세션 노트 로드

                if (result.chart_layout && result.chart_layout.length > 0) {
                    console.log('Restoring chart layout from database');
                    isRestoringLayout = true;
                    // Plot 탭으로 전환하여 차트 복원 준비
                    document.querySelector('[data-tab="plot"]').click();
                    
                    // 차트 레이아웃 복원 (DOM 렌더링 후 실행)
                    setTimeout(async () => {
                        await restoreChartLayout(result.chart_layout);
                        isRestoringLayout = false;
                    }, 100);
                } else {
                    // 복원할 레이아웃이 없으면 파일 탭으로 이동
                    document.querySelector('[data-tab="file"]').click();
                }
            } else {
                uploadStatus.textContent = 'File uploaded successfully!';
                clearTimeSegmentCache();
                const sessionNotesTextarea = document.getElementById('session-notes-textarea');
                if (sessionNotesTextarea) {
                    sessionNotesTextarea.value = '';
                }
                // 파일 탭으로 이동
                document.querySelector('[data-tab="file"]').click();
            }
            
            // 공통 성공 로직
            if (typeof updateGlobalTimeInfo === 'function') updateGlobalTimeInfo();
            const derivedParaBtn = document.getElementById('derived-para-btn');
            if (derivedParaBtn) {
                derivedParaBtn.disabled = false;
                derivedParaBtn.classList.remove('disabled');
                derivedParaBtn.classList.add('primary');
            }
            const timeSegmentBtn = document.getElementById('time-segment-btn');
            if (timeSegmentBtn) {
                timeSegmentBtn.disabled = false;
                timeSegmentBtn.classList.remove('disabled');
            }
        } else {
            throw new Error(result.error);
        }
    } catch (error) {
        uploadStatus.textContent = `Error: ${error.message}`;
        uploadStatus.className = 'error';
    }
});

// Fixed-wing upload handling
uploadFixedWingBtn.addEventListener('click', () => {
    // Fixed-wing 전용 파일 입력을 위한 임시 input 생성
    const fixedWingInput = document.createElement('input');
    fixedWingInput.type = 'file';
    fixedWingInput.accept = '.mat,.matlab,.csv,.db';
    fixedWingInput.style.display = 'none';
    
    fixedWingInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('file_type', 'fixed_wing'); // Fixed-wing 파일임을 표시

        try {
            uploadStatus.textContent = 'Uploading Fixed-wing File....';
            uploadStatus.className = 'uploading';
            
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (response.ok) {
                // 어떤 파일을 올리든, 성공 시 플롯 영역을 완전히 초기화
                resetPlotArea();

                uploadStatus.className = 'success';
                
                // 업로드된 파일명 표시
                const currentFileDiv = document.getElementById('current-file');
                currentFileDiv.innerHTML = `<strong>Current File (Fixed-wing):</strong><br>${escapeHtml(file.name)}`;
                currentFileDiv.style.display = 'block';
                setDatasetStatus(file.name);
                
                const fileExt = file.name.toLowerCase().split('.').pop();
                
                if (fileExt === 'db') {
                    uploadStatus.textContent = 'Fixed-wing database loaded successfully!';
                    loadSessionNotes(); // 세션 노트 로드

                    if (result.chart_layout && result.chart_layout.length > 0) {
                        console.log('Restoring chart layout from fixed-wing database');
                        isRestoringLayout = true;
                        // Plot 탭으로 전환하여 차트 복원 준비
                        document.querySelector('[data-tab="plot"]').click();
                        
                        // 차트 레이아웃 복원 (DOM 렌더링 후 실행)
                        setTimeout(async () => {
                            await restoreChartLayout(result.chart_layout);
                            isRestoringLayout = false;
                        }, 100);
                    } else {
                        // 복원할 레이아웃이 없으면 파일 탭으로 이동
                        document.querySelector('[data-tab="file"]').click();
                    }
                } else {
                    uploadStatus.textContent = 'Fixed-wing file uploaded successfully!';
                    clearTimeSegmentCache();
                    const sessionNotesTextarea = document.getElementById('session-notes-textarea');
                    if (sessionNotesTextarea) {
                        sessionNotesTextarea.value = '';
                    }
                    // 파일 탭으로 이동
                    document.querySelector('[data-tab="file"]').click();
                }
                
                // 공통 성공 로직
                if (typeof updateGlobalTimeInfo === 'function') updateGlobalTimeInfo();
                const derivedParaBtn = document.getElementById('derived-para-btn');
                if (derivedParaBtn) {
                    derivedParaBtn.disabled = false;
                    derivedParaBtn.classList.remove('disabled');
                    derivedParaBtn.classList.add('primary');
                }
                const timeSegmentBtn = document.getElementById('time-segment-btn');
                if (timeSegmentBtn) {
                    timeSegmentBtn.disabled = false;
                    timeSegmentBtn.classList.remove('disabled');
                }
            } else {
                throw new Error(result.error);
            }
        } catch (error) {
            uploadStatus.textContent = `Error: ${error.message}`;
            uploadStatus.className = 'error';
        }
        
        // 임시 input 제거
        document.body.removeChild(fixedWingInput);
    });
    
    // 임시 input을 body에 추가하고 클릭
    document.body.appendChild(fixedWingInput);
    fixedWingInput.click();
});

// Load parameters from backend
async function loadParameters() {
    await ensureConfigDataLoaded();
    try {
        const response = await fetch('/api/parameters');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        
        // Check if data is an array
        if (!Array.isArray(data)) {
            console.error('Received non-array data:', data);
            parametersList.innerHTML = '<div class="error-message">Invalid data format received</div>';
            return;
        }
        
        parameters = data;
        console.log('Received parameters:', parameters);
        if (parameters.length > 0) {
            const fileLabel = document.getElementById('status-file-name');
            setDatasetStatus(fileLabel?.textContent === 'NO DATASET' ? 'ACTIVE DATASET' : fileLabel?.textContent);
        }
        
        // Show Description 토글 상태 확인 (전역 변수 사용)
        const showDescription = isShowDescription;
        
        // configData에서 description 매핑
        let paramDescMap = {};
        if (window.configData && Array.isArray(window.configData)) {
            window.configData.forEach(cfg => {
                if (cfg.parameter_name) {
                    paramDescMap[cfg.parameter_name] = cfg.description || '';
                }
            });
        }
        
        if (parameters.length === 0) {
            parametersList.innerHTML = '<div class="info-message">No parameters found. Please upload a MATLAB file first.</div>';
            updateParameterResultCount(0, 0);
            // New Derived 버튼 비활성화
            const derivedParaBtn = document.getElementById('derived-para-btn');
            if (derivedParaBtn) {
                derivedParaBtn.disabled = true;
                derivedParaBtn.classList.add('disabled');
                derivedParaBtn.classList.remove('primary');
            }
            return;
        }
        
        parametersList.innerHTML = parameters.map(param => {
            const desc = paramDescMap[param] || '';
            const safeParam = escapeHtml(param);
            const safeDesc = escapeHtml(desc);
            const searchText = escapeHtml(`${param} ${desc}`.toLocaleLowerCase());
            if (showDescription && desc) {
                return `
                    <div class="parameter-item" data-parameter="${safeParam}" data-search="${searchText}" draggable="true" title="${safeDesc}">
                        <div class="parameter-name">${safeParam}</div>
                        <div class="parameter-description">${safeDesc}</div>
                    </div>
                `;
            } else {
                return `<div class="parameter-item" data-parameter="${safeParam}" data-search="${searchText}" draggable="true" title="${safeDesc}"><div class="parameter-name">${safeParam}</div></div>`;
            }
        }).join('');
        applyParameterFilter();
        
        // Add click handlers for parameters
        document.querySelectorAll('.parameter-item').forEach(item => {
            // Drag start handler
            item.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', item.dataset.parameter);
                e.dataTransfer.effectAllowed = 'copy';
            });

            item.addEventListener('click', (e) => {
                // 파생파라미터 에디터가 열려 있으면 에디터에만 삽입
                if (document.getElementById('derived-panel') && document.getElementById('derived-panel').classList.contains('visible')) {
                    if (window.monacoEditor) {
                        const text = item.dataset.parameter;
                        const editor = window.monacoEditor;
                        if (typeof editor.executeEdits === 'function' && typeof monaco !== 'undefined') {
                            const position = editor.getPosition();
                            editor.executeEdits('', [{
                                range: new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column),
                                text: text,
                                forceMoveMarkers: true
                            }]);
                        } else if (typeof editor.getValue === 'function' && typeof editor.setValue === 'function') {
                            editor.setValue(editor.getValue() + text);
                        }
                        editor.focus();
                    }
                } else if (selectedChart) {
                    updateChart(selectedChart, item.dataset.parameter);
                }
            });
        });

        // New Derived 버튼 활성화
        const derivedParaBtn = document.getElementById('derived-para-btn');
        if (derivedParaBtn) {
            derivedParaBtn.disabled = false;
            derivedParaBtn.classList.remove('disabled');
            derivedParaBtn.classList.add('primary');
        }
        
        // Time Segment 버튼 활성화
        const timeSegmentBtn = document.getElementById('time-segment-btn');
        if (timeSegmentBtn) {
            timeSegmentBtn.disabled = false;
            timeSegmentBtn.classList.remove('disabled');
        }
        
        // Data Tools 버튼 활성화
        const utilityAppsBtn = document.getElementById('utility-apps-btn');
        if (utilityAppsBtn) {
            utilityAppsBtn.disabled = false;
            utilityAppsBtn.classList.remove('disabled');
        }
    } catch (error) {
        console.error('Error loading parameters:', error);
            parametersList.innerHTML = '<div class="error-message">Failed to load parameters</div>';
            updateParameterResultCount(0, 0);
    }
}

// Show Description 토글 시 파라미터 리스트 갱신 (setupToggleEventListeners에서 처리됨)

// plot-area 스타일 설정 (Plot 탭에서만 적용)
(function() {
    const style = document.createElement('style');
    style.innerHTML = `
        #plot-area.show-for-plot {
            display: grid !important;
            grid-template-columns: repeat(4, 1fr);
            grid-template-rows: repeat(2, 1fr);
            width: 100vw;
            height: 100vh;
            gap: 8px;
            overflow: hidden;
        }
        .chart-container {
            width: 100%;
            height: 100%;
            min-width: 0;
            min-height: 0;
            box-sizing: border-box;
        }
    `;
    document.head.appendChild(style);
})();

// 최대 차트 개수
const MAX_CHARTS = 25;
const INITIAL_CHARTS = 4;

function updateGridLayout() {
    const plotArea = document.getElementById('plot-area');
    const chartCount = charts.length;
    if (!plotArea) return;

    let cols, rows;
    if (chartCount <= 4) { cols = 2; rows = 2; }
    else if (chartCount <= 9) { cols = 3; rows = 3; }
    else if (chartCount <= 16) { cols = 4; rows = 4; }
    else if (chartCount <= 20) { cols = 4; rows = 5; }
    else { cols = 5; rows = 5; }

    const gap = 2.5;
    const plotAreaStyle = getComputedStyle(plotArea);
    const paddingLeft = parseFloat(plotAreaStyle.paddingLeft);
    const paddingRight = parseFloat(plotAreaStyle.paddingRight);
    const totalPadding = paddingLeft + paddingRight;

    const plotAreaWidth = plotArea.clientWidth - totalPadding;
    const plotAreaHeight = plotArea.clientHeight;
    const chartWidth = (plotAreaWidth - gap * (cols - 1)) / cols;
    const chartHeight = (plotAreaHeight - gap * (rows - 1)) / rows;

    plotArea.style.gridTemplateColumns = Array(cols).fill(`${chartWidth}px`).join(' ');
    plotArea.style.gridTemplateRows = Array(rows).fill(`${chartHeight}px`).join(' ');
    plotArea.style.gap = `${gap}px`;

    charts.forEach((chart, idx) => {
        const container = document.getElementById(chart.id);
        if (container) {
            container.style.width = `${chartWidth}px`;
            container.style.height = `${chartHeight}px`;
            container.style.order = idx;

            // padding 고려
            const style = getComputedStyle(container);
            const paddingLeft = parseFloat(style.paddingLeft);
            const paddingRight = parseFloat(style.paddingRight);
            const paddingTop = parseFloat(style.paddingTop);
            const paddingBottom = parseFloat(style.paddingBottom);
            const plotWidth = chartWidth - paddingLeft - paddingRight;
            const plotHeight = chartHeight - paddingTop - paddingBottom;

            if (chart.plot) {
                chart.plot.setSize({
                    width: plotWidth,
                    height: plotHeight
                });
            }
        }
    });
}

function resetPlotArea() {
    // Destroy existing charts and clear the array
    if (charts && charts.length > 0) {
        charts.forEach(chart => {
            if (chart.plot) {
                chart.plot.destroy();
            }
        });
        console.log(`Destroyed ${charts.length} old charts.`);
    }
    charts = [];
    
    // Clear the DOM
    if (plotArea) {
        plotArea.innerHTML = '';
    }
    
    // Reset selection state
    selectedChart = null;
    selectedCharts = [];

    // Update UI elements that depend on chart selection
    updateButtonStates();
    
    console.log('Plot area has been fully reset.');
}

// 초기 6개 차트 자동 생성
window.addEventListener('DOMContentLoaded', () => {
    // Add CSS for context menu
    const style = document.createElement('style');
    style.innerHTML = `
        .context-menu {
            display: none;
            position: absolute;
            z-index: 1000;
            background-color: #fff;
            border: 1px solid #ccc;
            border-radius: 4px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.15);
            min-width: 150px;
            font-family: sans-serif;
            font-size: 14px;
        }
        .context-menu-item {
            padding: 8px 12px;
            cursor: pointer;
        }
        .context-menu-item:hover {
            background-color: #f0f0f0;
        }
        .context-menu-item[style*="color: #aaa"] {
            background-color: #fff;
        }
        .context-menu-divider {
            height: 1px;
            background-color: #eee;
            margin: 4px 0;
        }
    `;
    document.head.appendChild(style);

    // Add context menu HTML to body
    const contextMenuHTML = `
    <div id="chart-context-menu" class="context-menu">
        <!-- Items will be populated dynamically -->
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', contextMenuHTML);

    // 초기에는 차트를 생성하지 않음 (Plot 탭 선택 시에만 생성)
    updateGridLayout();

    // Add Derived Para button to toolbar if not present
    const toolbar = document.querySelector('.toolbar');
    const viewToolbarGroup = document.getElementById('view-toolbar-group') || toolbar;
    const analysisToolbarGroup = document.getElementById('analysis-toolbar-group') || toolbar;
    const dataToolbarGroup = document.getElementById('data-toolbar-group') || toolbar;
    let derivedParaBtn = document.getElementById('derived-para-btn');
    let timeSegmentBtn = null;
    if (toolbar && !derivedParaBtn) {
        derivedParaBtn = document.createElement('button');
        derivedParaBtn.className = 'btn btn-primary';
        derivedParaBtn.id = 'derived-para-btn';
        derivedParaBtn.textContent = 'New Derived';
        derivedParaBtn.onclick = function() {
            if (typeof window.showDerivedPanel === 'function') window.showDerivedPanel();
        };
        analysisToolbarGroup.appendChild(derivedParaBtn);

        // Time Segment 드롭다운 생성
        if (!document.getElementById('time-segment-dropdown')) {
            const timeSegmentDropdown = document.createElement('div');
            timeSegmentDropdown.className = 'filter-dropdown';
            timeSegmentDropdown.id = 'time-segment-dropdown';
            // 버튼
            timeSegmentBtn = document.createElement('button');
            timeSegmentBtn.id = 'time-segment-btn';
            timeSegmentBtn.className = 'btn';
            timeSegmentBtn.textContent = 'Time Segment';
            timeSegmentBtn.style.whiteSpace = 'nowrap'; // 줄바꿈 방지
            // 드롭다운 메뉴
            const dropdownContent = document.createElement('div');
            dropdownContent.className = 'dropdown-content';
            dropdownContent.innerHTML = `
                <a href="#" data-segment="set">Set segment</a>
                <a href="#" data-segment="select">Select segment</a>
            `;
            timeSegmentDropdown.appendChild(timeSegmentBtn);
            timeSegmentDropdown.appendChild(dropdownContent);
            dataToolbarGroup.insertBefore(timeSegmentDropdown, dataToolbarGroup.children[1] || null);
            // 드롭다운 토글: 마우스 오버 시 열림
            timeSegmentDropdown.addEventListener('mouseenter', function() {
                dropdownContent.style.display = 'block';
            });
            timeSegmentDropdown.addEventListener('mouseleave', function() {
                dropdownContent.style.display = 'none';
            });
            // 기존 클릭 토글 제거
            // 외부 클릭 시 닫기
            document.addEventListener('click', function(e) {
                if (!timeSegmentDropdown.contains(e.target)) {
                    dropdownContent.style.display = 'none';
                }
            });
            // 메뉴 클릭 핸들러(추후 구현)
            dropdownContent.querySelectorAll('a').forEach(link => {
                link.addEventListener('click', function(e) {
                    e.preventDefault();
                    // Set time segment 클릭 시 팝업 표시 및 값 자동 입력
                    if (link.dataset.segment === 'set') {
                        const popup = document.getElementById('time-segment-popup');
                        const form = document.getElementById('time-segment-form');
                        const nameInput = document.getElementById('segment-name');
                        const startInput = document.getElementById('segment-start');
                        const endInput = document.getElementById('segment-end');
                        // 현재 선택된 차트의 X축(min/max) 값 입력 (초단위, 정수)
                        let min = '';
                        let max = '';
                        if (selectedChart) {
                            const chart = charts.find(c => c.id === selectedChart);
                            if (chart && chart.plot && chart.plot.scales && chart.plot.scales.x) {
                                min = Math.round(chart.plot.scales.x.min);
                                max = Math.round(chart.plot.scales.x.max);
                            }
                        }
                        nameInput.value = '';
                        startInput.value = min;
                        endInput.value = max;
                        popup.style.display = 'flex';
                        // 닫기 버튼 핸들러
                        popup.querySelector('.close-btn').onclick = () => { popup.style.display = 'none'; };
                        // 폼 제출 시 팝업 닫기(실제 저장 로직은 추후 구현)
                        form.onsubmit = (ev) => {
                            ev.preventDefault();
                            // 저장 API 호출
                            fetch('/api/time_segment', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    name: nameInput.value,
                                    start: Number(startInput.value),
                                    end: Number(endInput.value)
                                })
                            }).then(res => res.json()).then(data => {
                                if (data.success) {
                                    popup.style.display = 'none';
                                } else {
                                    alert('세그먼트 저장 실패: ' + (data.error || 'Unknown error'));
                                }
                            }).catch(err => {
                                alert('세그먼트 저장 실패: ' + err);
                            });
                        };
                    }
                    // Select time segment 클릭 시 목록 팝업
                    if (link.dataset.segment === 'select') {
                        fetch('/api/time_segment').then(res => res.json()).then(segments => {
                            if (!Array.isArray(segments) || segments.length === 0) {
                                alert('저장된 세그먼트가 없습니다.');
                                return;
                            }
                            // 팝업 생성
                            let popup = document.getElementById('time-segment-popup');
                            if (!popup) return;
                            popup.style.display = 'flex';
                            // 팝업 타이틀 변경
                            popup.querySelector('.popup-header h3').textContent = 'Select segment';
                            const form = document.getElementById('time-segment-form');
                            form.style.display = 'none';
                            // 기존 목록 제거
                            let listDiv = popup.querySelector('.segment-list');
                            if (listDiv) listDiv.remove();
                            listDiv = document.createElement('div');
                            listDiv.className = 'segment-list';
                            listDiv.style.marginTop = '10px';
                            listDiv.innerHTML = segments.map(seg =>
                                `<div class="segment-item" style="display: flex; align-items: center; margin-bottom: 8px; gap: 8px;">
                                    <button class="btn segment-select-btn" data-start="${seg.start}" data-end="${seg.end}" style="flex: 1;">${seg.name} (${Math.round(seg.start)} ~ ${Math.round(seg.end)}s)</button>
                                    <button class="btn segment-delete-btn" data-id="${seg.id}" data-name="${seg.name}" style="background-color: #dc3545; color: white; padding: 4px 8px; font-size: 0.8em;">삭제</button>
                                </div>`
                            ).join('');
                            popup.querySelector('.popup-content').appendChild(listDiv);
                            // 닫기 버튼
                            popup.querySelector('.close-btn').onclick = () => {
                                popup.style.display = 'none';
                                form.style.display = '';
                                // 팝업 타이틀 원복
                                popup.querySelector('.popup-header h3').textContent = 'Set segment';
                                listDiv.remove();
                            };
                            // 선택 버튼 핸들러
                            listDiv.querySelectorAll('.segment-select-btn').forEach(btn => {
                                btn.onclick = () => {
                                    const start = Number(btn.dataset.start);
                                    const end = Number(btn.dataset.end);
                                    // 모든 차트 X축 스케일 조정
                                    charts.forEach(chart => {
                                        if (chart.plot && chart.plot.setScale) {
                                            chart.plot.setScale('x', { min: start, max: end });
                                            chart.lastZoom = { min: start, max: end };
                                            chart.lastScale = { min: start, max: end };
                                        }
                                    });
                                    popup.style.display = 'none';
                                    form.style.display = '';
                                    // 팝업 타이틀 원복
                                    popup.querySelector('.popup-header h3').textContent = 'Set segment';
                                    listDiv.remove();
                                };
                            });
                            // 삭제 버튼 핸들러
                            listDiv.querySelectorAll('.segment-delete-btn').forEach(btn => {
                                btn.onclick = () => {
                                    const segmentId = Number(btn.dataset.id);
                                    const segmentName = btn.dataset.name;
                                    if (confirm(`"${segmentName}" 세그먼트를 삭제하시겠습니까?`)) {
                                        fetch(`/api/time_segment/${segmentId}`, {
                                            method: 'DELETE'
                                        }).then(res => res.json()).then(data => {
                                            if (data.success) {
                                                // 삭제된 세그먼트를 목록에서 제거
                                                btn.closest('.segment-item').remove();
                                                // 목록이 비어있으면 팝업 닫기
                                                if (listDiv.querySelectorAll('.segment-item').length === 0) {
                                                    popup.style.display = 'none';
                                                    form.style.display = '';
                                                    popup.querySelector('.popup-header h3').textContent = 'Set segment';
                                                    listDiv.remove();
                                                }
                                            } else {
                                                alert('세그먼트 삭제 실패: ' + (data.error || 'Unknown error'));
                                            }
                                        }).catch(err => {
                                            alert('세그먼트 삭제 실패: ' + err);
                                        });
                                    }
                                };
                            });
                        });
                    }
                    dropdownContent.style.display = 'none';
                });
            });
        }
    } else {
        // 이미 존재하는 경우에도 참조
        timeSegmentBtn = document.getElementById('time-segment-btn');
    }

    // Data utility: BIT extractor
    if (!document.getElementById('utility-apps-btn')) {
        const utilityAppsBtn = document.createElement('button');
        utilityAppsBtn.id = 'utility-apps-btn';
        utilityAppsBtn.className = 'btn';
        utilityAppsBtn.textContent = 'BIT Extractor';
        utilityAppsBtn.style.whiteSpace = 'nowrap';
        utilityAppsBtn.addEventListener('click', showBitExtractorPopup);
        dataToolbarGroup.appendChild(utilityAppsBtn);

        // Canvas Button 생성
        if (!document.getElementById('canvas-btn')) {
            const canvasBtn = document.createElement('button');
            canvasBtn.id = 'canvas-btn';
            canvasBtn.className = 'btn';
            canvasBtn.textContent = 'Canvas';
            canvasBtn.style.whiteSpace = 'nowrap';
            
            viewToolbarGroup.appendChild(canvasBtn);
            canvasBtn.addEventListener('click', toggleCanvasMode);
        }
    }

    // 초기 비활성화 버튼들
    scaleBtn.disabled = true;
    scaleBtn.classList.add('disabled');
    minmaxBtn.disabled = true;
    minmaxBtn.classList.add('disabled');
    fftBtn.disabled = true;
    fftBtn.classList.add('disabled');
    scatterBtn.disabled = true;
    scatterBtn.classList.add('disabled');
    filterBtn.disabled = true;
    filterBtn.classList.add('disabled');
    if (derivedParaBtn) {
        derivedParaBtn.disabled = true;
        derivedParaBtn.classList.add('disabled');
    }
    if (timeSegmentBtn) {
        timeSegmentBtn.disabled = true;
        timeSegmentBtn.classList.add('disabled');
    }
    // Utility Apps 버튼 초기 비활성화
    const utilityAppsBtn = document.getElementById('utility-apps-btn');
    if (utilityAppsBtn) {
        utilityAppsBtn.disabled = true;
        utilityAppsBtn.classList.add('disabled');
    }

    updateGlobalTimeInfo();
});

// Add Chart 버튼 클릭 시 최대 25개까지 추가
addChartBtn.addEventListener('click', () => {
    if (isCanvasMode) {
        addCanvasChart();
    } else {
        if (charts.length < MAX_CHARTS) {
            createChart();
            updateGridLayout();
        }
    }
});

// 차트 삭제 시 빈 타일 유지 (DOM에서만 제거, grid cell은 유지)
window.addEventListener('keydown', (e) => {
    if (e.key === 'Delete' && (selectedChart || selectedCharts.length > 0)) {
        // 여러 차트가 선택된 경우 모든 선택된 차트 삭제
        const chartsToDelete = selectedCharts.length > 0 ? selectedCharts : [selectedChart];
        
        chartsToDelete.forEach(chartId => {
            if (chartId) {
                const chartIdx = charts.findIndex(c => c.id === chartId);
                if (chartIdx !== -1) {
                    const chartContainer = document.getElementById(chartId);
                    if (chartContainer) {
                        chartContainer.remove();
                    }
                    if (charts[chartIdx].plot && charts[chartIdx].plot.destroy) {
                        charts[chartIdx].plot.destroy();
                    }
                    charts.splice(chartIdx, 1);
                }
            }
        });
        
        // 선택 상태 초기화
        selectedChart = null;
        selectedCharts = [];
        updateButtonStates();
        updateGridLayout();
    }
    
    // 화살표 키로 모든 차트 x축 이동
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        // 텍스트 입력 필드에서 화살표 키는 차단하지 않음
        const activeElement = document.activeElement;
        const isTextInput = ['INPUT', 'TEXTAREA'].includes(activeElement.tagName) || 
                           activeElement.isContentEditable || 
                           activeElement.classList.contains('monaco-editor');
        
        if (isTextInput) {
            return; // 텍스트 입력 필드에서는 화살표 키를 허용
        }
        
        e.preventDefault();
        
        // 데이터가 있는 차트들만 필터링
        const chartsWithData = charts.filter(chart => 
            chart.plot && chart.data.time && chart.data.time.length > 0
        );
        
        if (chartsWithData.length === 0) return;
        
        // 첫 번째 차트의 현재 스케일을 기준으로 이동 거리 계산
        const firstChart = chartsWithData[0];
        const currentScale = firstChart.plot.scales.x;
        const currentMin = currentScale.min;
        const currentMax = currentScale.max;
        const currentRange = currentMax - currentMin;
        
        // 그리드 두 개 분량의 이동 거리 계산
        // 현재 x축 범위를 10등분하여 2등분만큼 이동 (그리드 기반)
        const gridCount = 10; // 그리드 개수
        const gridWidth = currentRange / gridCount; // 그리드 하나의 너비
        const moveDistance = gridWidth * 2; // 그리드 두 개 분량
        
        let newMin, newMax;
        if (e.key === 'ArrowLeft') {
            // 왼쪽으로 이동 (시간이 작아지는 방향)
            newMin = currentMin - moveDistance;
            newMax = currentMax - moveDistance;
        } else {
            // 오른쪽으로 이동 (시간이 커지는 방향)
            newMin = currentMin + moveDistance;
            newMax = currentMax + moveDistance;
        }
        
        // 모든 차트에 동일한 스케일 적용
        chartsWithData.forEach(chart => {
            // 각 차트의 데이터 범위를 벗어나지 않도록 제한 (대용량 데이터 처리)
            let dataMin = Infinity;
            let dataMax = -Infinity;
            
            // 배열이 너무 큰 경우 샘플링하여 최소/최대값 계산
            const timeArray = chart.data.time;
            const arrayLength = timeArray.length;
            
            if (arrayLength > 10000) {
                // 대용량 데이터의 경우 샘플링
                const step = Math.max(1, Math.floor(arrayLength / 10000));
                for (let i = 0; i < arrayLength; i += step) {
                    const val = timeArray[i];
                    if (val < dataMin) dataMin = val;
                    if (val > dataMax) dataMax = val;
                }
            } else {
                // 소용량 데이터의 경우 전체 검사
                for (let i = 0; i < arrayLength; i++) {
                    const val = timeArray[i];
                    if (val < dataMin) dataMin = val;
                    if (val > dataMax) dataMax = val;
                }
            }
            
            let chartNewMin = newMin;
            let chartNewMax = newMax;
            
            if (chartNewMin < dataMin) {
                chartNewMin = dataMin;
                chartNewMax = chartNewMin + currentRange;
            }
            if (chartNewMax > dataMax) {
                chartNewMax = dataMax;
                chartNewMin = chartNewMax - currentRange;
            }
            
            // Fixed Scale이 활성화된 경우 Y축 스케일을 유지
            if (isFixedScale) {
                // 현재 Y축 스케일을 유지하면서 X축만 업데이트
                const currentYScale = chart.plot.scales.y;
                chart.plot.setScale('x', { min: chartNewMin, max: chartNewMax });
                // Y축 스케일을 명시적으로 다시 설정하여 자동 조정 방지
                chart.plot.setScale('y', { min: currentYScale.min, max: currentYScale.max });
            } else {
                // Fixed Scale이 비활성화된 경우 일반적인 업데이트
                chart.plot.setScale('x', { min: chartNewMin, max: chartNewMax });
            }
        });
    }
});

// 창 크기 변경 시 차트 크기 자동 조정
let resizeTimeout;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        updateGridLayout();
    }, 100); // 디바운스 처리
});

// Chart management
function createChart() {
    const chartId = `chart-${Date.now()}`;
    const chartContainer = document.createElement('div');
    chartContainer.className = 'chart-container';
    chartContainer.id = chartId;
    chartContainer.style.height = '290px';
    chartContainer.style.order = charts.length; // order 속성 부여
    
    // 드래그 앤 드롭 속성 및 이벤트 추가
    chartContainer.setAttribute('draggable', 'true');
    chartContainer.addEventListener('dragstart', handleDragStart);
    chartContainer.addEventListener('dragover', handleDragOver);
    chartContainer.addEventListener('drop', handleDrop);
    chartContainer.addEventListener('dragend', handleDragEnd);
    
    // Shift 키를 누르고 있을 때는 uPlot 줌/드래그(마우스 드래그) 동작을 막음 (chartElement에만 적용)
    chartContainer.addEventListener('mousedown', function(e) {
        if (e.shiftKey) {
            e.stopPropagation();
            e.preventDefault();
        }
    }, true);

    // Double-click to reset zoom
    chartContainer.addEventListener('dblclick', () => {
        const chart = charts.find(c => c.id === chartId);
        if (chart && chart.initialScale) {
            chart.plot.setScale('x', chart.initialScale);
            // Re-fetch overview data for the full range
            const overviewResolution = 2000;
            updateChartData(chartId, chart.parameters, chart.initialScale.min, chart.initialScale.max, overviewResolution);
        }
    });
    
    const chartTitle = document.createElement('div');
    chartTitle.className = 'chart-title';
    chartTitle.textContent = 'Click to select, then choose a parameter';

    const chartHeader = document.createElement('div');
    chartHeader.className = 'chart-header';
    const dragHandle = document.createElement('span');
    dragHandle.className = 'chart-drag-handle';
    dragHandle.textContent = '••';
    dragHandle.title = 'Drag to reorder chart';
    const channelCount = document.createElement('span');
    channelCount.className = 'chart-channel-count';
    channelCount.textContent = 'EMPTY';
    chartHeader.appendChild(dragHandle);
    chartHeader.appendChild(chartTitle);
    chartHeader.appendChild(channelCount);
    
    const chartElement = document.createElement('div');
    chartElement.className = 'chart-plot';
    chartElement.style.width = '100%';
    chartElement.style.height = '250px';
    
    chartContainer.appendChild(chartHeader);
    chartContainer.appendChild(chartElement);
    
    // Add context menu listener for deleting parameters
    chartContainer.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showContextMenu(e, chartId);
    });

    // Add click handler for chart selection
    chartContainer.addEventListener('click', (e) => {
        if (e.ctrlKey) {
            // Ctrl+클릭으로 여러 차트 선택
            if (chartContainer.classList.contains('selected')) {
                chartContainer.classList.remove('selected', 'multi-selected');
                selectedCharts = selectedCharts.filter(id => id !== chartId);
            } else {
                chartContainer.classList.add('selected');
                selectedCharts.push(chartId);
            }
            selectedChart = chartId;
            
            // 여러 차트가 선택된 경우 multi-selected 클래스 추가
            if (selectedCharts.length > 1) {
                document.querySelectorAll('.chart-container.selected').forEach(container => {
                    container.classList.add('multi-selected');
                });
            } else {
                document.querySelectorAll('.chart-container').forEach(container => {
                    container.classList.remove('multi-selected');
                });
            }
        } else {
            // 일반 클릭으로 단일 차트 선택
            document.querySelectorAll('.chart-container').forEach(c => {
                c.classList.remove('selected', 'multi-selected');
            });
            chartContainer.classList.add('selected');
            selectedChart = chartId;
            selectedCharts = [chartId];
        }
        updateButtonStates();
    });
    
    plotArea.appendChild(chartContainer);
    
    // Create uPlot instance with empty data
    const opts = {
        width: chartElement.offsetWidth,
        height: 250,
        title: '',
        cursor: {
            show: true,
            sync: {
                key: 'shared',
            },
            drag: {
                setScale: true,
                x: true,
                y: false,
            },
        },
        scales: {
            x: {
                time: false,
                auto: false,
            },
            y: {
                auto: true,
            },
        },
        axes: [
            {
                scale: 'x',
                label: '',
                stroke: '#000',
                size: 30,
                labelSize: 0,
                labelGap: 0,
                padding: 0,
                values: (u, ticks) => {
                    if (!ticks || ticks.length < 2) return ticks;
                    const interval = Math.abs(ticks[1] - ticks[0]);
                    let decimals = 0;
                    if (interval < 0.1) decimals = 3;
                    else if (interval < 1) decimals = 2;
                    else if (interval < 10) decimals = 1;
                    else decimals = 0;
                    return ticks.map(v => v.toFixed(decimals));
                }
            },
            { scale: 'y', label: '', stroke: '#2196F3', size: 40, labelSize: 0, labelGap: 0, padding: 0 }
        ],
        series: [
            { label: 'Time' },
            { label: '', stroke: '#2196F3', scale: 'y' },
            { label: '', stroke: '#FF5722', scale: 'y' },
            { label: '', stroke: '#4CAF50', scale: 'y' }
        ],
        padding: [10, 10, 10, 10],
        hooks: {
            setSelect: [(u) => {
                /*
                const chart = charts.find(c => c.id === chartId);
                if (!chart || u.cursor.left < 0) return; // Ignore if chart not found or selection is being cleared

                clearTimeout(chart.updateTimeout);

                const min = u.scales.x.min;
                const max = u.scales.x.max;

                // Avoid re-fetching on simple clicks or tiny drags
                if (max - min < 1e-6) return;

                chart.updateTimeout = setTimeout(() => {
                    console.log(`Zoom event on ${chartId}: ${min} to ${max}`);
                    const resolution = Math.floor(chart.plot.width * 2);
                    updateChartData(chartId, chart.parameters, min, max, resolution);
                }, 500); // 500ms debounce to prevent rapid-fire requests
                */
            }]
        }
    };
    
    // 초기 데이터 설정 (빈 배열로 시작)
    const initialData = [
        new Float64Array(0), // 시간 데이터
        new Float64Array(0), // 값 1
        new Float64Array(0), // 값 2
        new Float64Array(0)  // 값 3
    ];
    
    const plot = new uPlot(opts, initialData, chartElement);
    
    // 차트 객체 생성 및 초기화
    const chartObj = {
        id: chartId,
        plot,
        parameters: [],
        currentLevel: 0,
        lastZoom: null,
        updateTimeout: null,
        lastScale: null,
        lastUpdateTime: 0,
        isUpdating: false,
        isRestoringZoom: false,
        initialScale: null,
        data: {
            time: new Float64Array(0),
            values: [new Float64Array(0), new Float64Array(0), new Float64Array(0)]
        }
    };
    
    charts.push(chartObj);
    
    return chartId;
}

// Context Menu Functions for deleting parameters
function showContextMenu(event, chartId) {
    const contextMenu = document.getElementById('chart-context-menu');
    const chart = charts.find(c => c.id === chartId);
    if (!chart) return;

    const menu = contextMenu;
    menu.innerHTML = ''; // Clear previous items

    const createMenuItem = (text, onClick, enabled = true) => {
        const item = document.createElement('div');
        item.className = 'context-menu-item';
        item.textContent = text;
        if (enabled) {
            item.onclick = (e) => {
                e.stopPropagation();
                hideContextMenu();
                onClick();
            };
        } else {
            item.style.color = '#aaa';
            item.style.cursor = 'default';
        }
        return item;
    };

    const hasParams = chart.parameters.length > 0;
    menu.appendChild(createMenuItem('Delete All Param', () => deleteParameter(chartId, 'all'), hasParams));
    
    const divider = document.createElement('div');
    divider.className = 'context-menu-divider';
    menu.appendChild(divider);

    menu.appendChild(createMenuItem('Delete Param 1', () => deleteParameter(chartId, 0), chart.parameters.length >= 1));
    menu.appendChild(createMenuItem('Delete Param 2', () => deleteParameter(chartId, 1), chart.parameters.length >= 2));
    menu.appendChild(createMenuItem('Delete Param 3', () => deleteParameter(chartId, 2), chart.parameters.length >= 3));

    menu.style.left = `${event.clientX}px`;
    menu.style.top = `${event.clientY}px`;
    menu.style.display = 'block';

    // Hide on next click
    setTimeout(() => {
        window.addEventListener('click', hideContextMenu, { once: true });
    }, 100);
}

function hideContextMenu() {
    const contextMenu = document.getElementById('chart-context-menu');
    if (contextMenu) {
        contextMenu.style.display = 'none';
    }
}

async function deleteParameter(chartId, paramIndex) {
    const chart = charts.find(c => c.id === chartId);
    if (!chart) return;

    if (paramIndex === 'all') {
        chart.parameters = [];
    } else {
        chart.parameters.splice(paramIndex, 1);
    }

    if (chart.parameters.length === 0) {
        // Clear the chart data
        const emptyData = [
            new Float64Array(0),
            new Float64Array(0),
            new Float64Array(0),
            new Float64Array(0)
        ];
        chart.plot.setData(emptyData);
        chart.data = {
            time: new Float64Array(0),
            values: [new Float64Array(0), new Float64Array(0), new Float64Array(0)]
        };
        
        // Reset title
        const chartContainer = document.getElementById(chartId);
        const titleElement = chartContainer.querySelector('.chart-title');
        titleElement.textContent = 'Click to select, then choose a parameter';
        
        // Reset Y-axis scale to auto
        chart.plot.setScale('y', { min: null, max: null });

    } else {
        // Refetch data for remaining parameters
        const currentScale = chart.plot.scales.x;
        await updateChartData(chartId, chart.parameters, currentScale.min, currentScale.max);
    }
    
    // Update chart title and button states
    updateChartTitle(chart);
    updateButtonStates();
}

// 스케일 차이 계산 함수 최적화
function calculateScaleDifference(data1, data2) {
    if (!data1 || !data2 || data1.length === 0 || data2.length === 0) return 0;
    
    // 데이터가 너무 큰 경우 샘플링
    const maxSamples = 1000;
    const step1 = Math.max(1, Math.floor(data1.length / maxSamples));
    const step2 = Math.max(1, Math.floor(data2.length / maxSamples));
    
    // 샘플링된 데이터로 최소/최대값 계산
    let min1 = Infinity, max1 = -Infinity;
    let min2 = Infinity, max2 = -Infinity;
    
    for (let i = 0; i < data1.length; i += step1) {
        const val = data1[i];
        if (val < min1) min1 = val;
        if (val > max1) max1 = val;
    }
    
    for (let i = 0; i < data2.length; i += step2) {
        const val = data2[i];
        if (val < min2) min2 = val;
        if (val > max2) max2 = val;
    }
    
    const range1 = max1 - min1;
    const range2 = max2 - min2;
    
    // 범위가 0인 경우 처리
    if (range1 === 0 || range2 === 0) return 0;
    
    // 두 범위의 비율 계산
    const ratio = Math.max(range1, range2) / Math.min(range1, range2);
    return ratio;
}

// 차트 데이터 업데이트 함수 수정
async function updateChartData(chartId, parameters, start, end, resolution) {
    const chart = charts.find(c => c.id === chartId);
    if (!chart || !parameters || parameters.length === 0) return;

    try {
        const startParam = (start === undefined || start === null) ? -Infinity : start;
        const endParam = (end === undefined || end === null) ? Infinity : end;

        if (chart.isUpdating) {
            console.log('Update already in progress, skipping...');
            return;
        }
        chart.isUpdating = true;

        const chartContainer = document.getElementById(chartId);
        const titleElement = chartContainer?.querySelector('.chart-title');
        if (titleElement) {
            titleElement.innerHTML = `<span style="color: #1976d2; font-style: italic;">Loading Data...</span>`;
        }

        try {
            const dataPromises = parameters.map(param => fetchChartData(param, startParam, endParam, resolution));
            const allData = await Promise.all(dataPromises);

            const timeData = allData.length > 0 ? new Float64Array(allData[0].time) : new Float64Array(0);
            // Each channel can have a different native sample clock.  Align
            // every series to the first channel before handing it to uPlot.
            const valueData = allData.map(data => alignSeries(timeData, data.time, data.value));

            chart.data = { time: timeData, values: valueData };

            // Ensure data array is padded to match the number of series (1 time + 3 values)
            const plotData = [timeData];
            for (let i = 0; i < 3; i++) {
                plotData.push(valueData[i] || new Float64Array(0));
            }

            chart.plot.setData(plotData);

            if (isFixedScale && parameters.length >= 1) {
                const config = (window.configData || []).find(c => c.parameter_name === parameters[0]);
                if (config && isFinite(Number(config.lo)) && isFinite(Number(config.hi))) {
                    chart.plot.setScale('y', { min: Number(config.lo), max: Number(config.hi) });
                }
            }

        } finally {
            chart.isUpdating = false;
            updateChartTitle(chart);
        }
    } catch (error) {
        console.error('Error updating chart data:', error);
        chart.isUpdating = false;
        const chartContainer = document.getElementById(chartId);
        if (chartContainer) {
            const titleElement = chartContainer.querySelector('.chart-title');
            if (titleElement) {
                titleElement.textContent = `Error: ${error.message}`;
            }
        }
    }
}

async function updateChart(chartId, parameter) {
    const chart = charts.find(c => c.id === chartId);
    if (!chart) return;

    try {
        if (!chart.parameters.includes(parameter) && chart.parameters.length < 3) {
            chart.parameters.push(parameter);
        }

        updateChartTitle(chart);

        // Fetch a bounded overview; raw samples are requested only by an
        // analysis operation that explicitly needs them.
        const overviewResolution = 2000;
        const data = await fetchChartData(parameter, -Infinity, Infinity, overviewResolution);

        if (data.time && data.time.length > 0) {
            const initialScale = {
                min: data.firstTimestamp,
                max: data.lastTimestamp
            };

            chart.initialScale = initialScale;
            chart.lastZoom = initialScale;

            // Update the chart with the full data
            await updateChartData(chartId, chart.parameters, initialScale.min, initialScale.max, overviewResolution);

            chart.plot.setScale('x', initialScale);

            console.log('Initial scale set with overview data:', {
                chartId,
                parameters: chart.parameters,
                min: initialScale.min,
                max: initialScale.max
            });
        }
    } catch (error) {
        console.error('Error updating chart:', error);
        const chartContainer = document.getElementById(chartId);
        const titleElement = chartContainer.querySelector('.chart-title');
        titleElement.textContent = `Error: ${error.message}`;
    }
    updateButtonStates();
}

function alignSeries(referenceTime, sourceTime, sourceValues, policy = alignmentPolicy) {
    const out = new Float64Array(referenceTime.length);
    out.fill(NaN);
    if (!sourceTime || !sourceValues || sourceTime.length === 0) return out;
    const t = sourceTime;
    const v = sourceValues;
    let j = 0;
    for (let i = 0; i < referenceTime.length; i++) {
        const x = referenceTime[i];
        while (j + 1 < t.length && t[j + 1] <= x) j++;
        if (j >= t.length || x < t[0] || x > t[t.length - 1]) continue;
        const v0 = Number(v[j]);
        if (!Number.isFinite(v0)) continue;
        if (policy === 'hold-last' || j + 1 >= t.length || t[j + 1] === t[j]) {
            out[i] = v0;
            continue;
        }
        const v1 = Number(v[j + 1]);
        if (!Number.isFinite(v1)) { out[i] = v0; continue; }
        if (policy === 'nearest') {
            out[i] = (x - t[j] <= t[j + 1] - x) ? v0 : v1;
        } else {
            out[i] = v0 + (v1 - v0) * (x - t[j]) / (t[j + 1] - t[j]);
        }
    }
    return out;
}

async function fetchChartData(parameter, start, end, resolution) {
    const startParam = (start === null || start === undefined) ? -Infinity : start;
    const endParam = (end === null || end === undefined) ? Infinity : end;
    
    let url = `/api/data?parameter=${encodeURIComponent(parameter)}&start=${startParam}&end=${endParam}`;
    if (resolution === 0) {
        url += '&raw=1';
    } else if (resolution !== null && resolution !== undefined) {
        url += `&resolution=${resolution}`;
    }

    try {
        const response = await fetch(url);
        if (!response.ok) {
            const errorData = await response.json();
            console.error('Error fetching data:', errorData.error);
            throw new Error(errorData.error || 'Failed to fetch chart data');
        }
        const data = await response.json();

        if (!data.time || !data.value) {
            console.warn('No data available for this parameter in the given range');
            return { time: [], value: [], firstTimestamp: start, lastTimestamp: end };
        }

        const firstTimestamp = data.time.length > 0 ? data.time[0] : start;
        const lastTimestamp = data.time.length > 0 ? data.time[data.time.length - 1] : end;

        console.log(`Received ${data.time.length} data points for ${parameter}`);

        return {
            ...data,
            firstTimestamp,
            lastTimestamp
        };
    } catch (error) {
        console.error('Error in fetchChartData:', error);
        throw error;
    }
}

// FFT 분석 함수
async function performFFTAnalysis(chartId) {
    const chart = charts.find(c => c.id === chartId);
    if (!chart || chart.parameters.length !== 1) return;

    try {
        // 현재 보여지는 시간 영역대 가져오기
        const currentScale = chart.plot.scales.x;
        const start = currentScale.min;
        const end = currentScale.max;

        const fftResult = await runBackgroundJob('fft', {
            parameter: chart.parameters[0], start, end
        });
        
        // FFT 차트 생성
        createFFTChart(fftResult.frequencies, fftResult.magnitudes, chart.parameters[0]);
        
        // 팝업 표시
        fftPopup.style.display = 'flex';
    } catch (error) {
        console.error('Error performing FFT analysis:', error);
        alert('Error performing FFT analysis: ' + error.message);
    }
}

function simpleFFT(real, imag) {
    const n = real.length;
    if (n <= 1) return { real, imag };

    // 짝수/홀수 인덱스 분리
    const evenReal = new Float64Array(n/2);
    const evenImag = new Float64Array(n/2);
    const oddReal = new Float64Array(n/2);
    const oddImag = new Float64Array(n/2);
    
    for (let i = 0; i < n/2; i++) {
        evenReal[i] = real[i * 2];
        evenImag[i] = imag[i * 2];
        oddReal[i] = real[i * 2 + 1];
        oddImag[i] = imag[i * 2 + 1];
    }

    // 재귀적으로 FFT 계산
    const even = simpleFFT(evenReal, evenImag);
    const odd = simpleFFT(oddReal, oddImag);

    // 결과 합치기
    const resultReal = new Float64Array(n);
    const resultImag = new Float64Array(n);
    
    for (let k = 0; k < n/2; k++) {
        const angle = -2 * Math.PI * k / n;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        const oddRealK = odd.real[k];
        const oddImagK = odd.imag[k];
        
        resultReal[k] = even.real[k] + cos * oddRealK - sin * oddImagK;
        resultImag[k] = even.imag[k] + sin * oddRealK + cos * oddImagK;
        resultReal[k + n/2] = even.real[k] - (cos * oddRealK - sin * oddImagK);
        resultImag[k + n/2] = even.imag[k] - (sin * oddRealK + cos * oddImagK);
    }

    return { real: resultReal, imag: resultImag };
}

function calculateFFT(time, values) {
    const finite = values.map((v, i) => [Number(time[i]), Number(v)])
        .filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v));
    if (finite.length < 4) throw new Error('At least four finite samples are required for FFT');
    const t = finite.map(p => p[0]);
    const x = finite.map(p => p[1]);
    const dts = [];
    for (let i = 1; i < t.length; i++) dts.push(t[i] - t[i - 1]);
    const dt = dts.slice().sort((a, b) => a - b)[Math.floor(dts.length / 2)];
    if (!(dt > 0) || dts.some(d => Math.abs(d - dt) > dt * 0.01)) {
        throw new Error('FFT requires a nearly uniform time axis');
    }
    // Keep browser work bounded and use a Hann window to reduce leakage.
    const sampleCount = Math.min(x.length, 262144);
    const n = Math.pow(2, Math.floor(Math.log2(sampleCount)));
    const real = new Float64Array(n);
    const imag = new Float64Array(n);
    const mean = x.slice(0, n).reduce((a, b) => a + b, 0) / n;
    for (let i = 0; i < n; i++) {
        const w = 0.5 * (1 - Math.cos(2 * Math.PI * i / (n - 1)));
        real[i] = (x[i] - mean) * w;
        imag[i] = 0;
    }
    
    // FFT 수행
    const result = simpleFFT(real, imag);
    
    // 주파수 계산
    const frequencies = new Float64Array(n/2);
    const magnitudes = new Float64Array(n/2);
    
    for (let i = 0; i < n/2; i++) {
        frequencies[i] = i / (n * dt);
        magnitudes[i] = 2 * Math.sqrt(result.real[i] * result.real[i] + result.imag[i] * result.imag[i]) / n;
    }
    
    return { frequencies, magnitudes };
}

// FFT 차트 생성 함수
function createFFTChart(frequencies, magnitudes, parameter) {
    console.log('Creating FFT chart with:', { frequencies, magnitudes, parameter });
    
    if (fftChart) {
        fftChart.destroy();
    }
    
    // 차트 컨테이너 크기 확인
    const containerWidth = fftChartElement.offsetWidth || 800;
    const containerHeight = 400;
    
    const opts = {
        width: containerWidth,
        height: containerHeight,
        title: `FFT Analysis - ${parameter}`,
        cursor: {
            show: true,
        },
        scales: {
            x: {
                time: false,
                auto: true,
            },
            y: {
                auto: true,
            },
        },
        series: [
            {
                label: 'Frequency',
                value: (u, v) => v == null ? "-" : v.toFixed(2) + " Hz",
            },
            {
                label: 'Magnitude',
                stroke: '#2196F3',
                width: 1,
                value: (u, v) => v == null ? "-" : v.toFixed(2),
            },
        ],
        padding: [10, 10, 10, 10],
        axes: [
            {
                stroke: '#000',
                grid: { show: true },
                ticks: { show: true },
                size: 30,
                label: '',
                labelSize: 20,
                labelGap: 0,
                labelOffset: 0,
                labelFont: '12px Arial',
            },
            {
                stroke: '#000',
                grid: { show: true },
                ticks: { show: true },
                size: 30,
                label: '',
                labelSize: 20,
                labelGap: 0,
                labelOffset: 0,
                labelFont: '12px Arial',
            }
        ],
    };
    
    try {
        // 차트 생성 전에 컨테이너가 보이도록 설정
        fftChartElement.style.display = 'block';
        fftChartElement.style.width = '100%';
        fftChartElement.style.height = '400px';
        
        fftChart = new uPlot(opts, [frequencies, magnitudes], fftChartElement);
        console.log('FFT chart created successfully');
        
        // 차트 생성 후 크기 조정
        setTimeout(() => {
            if (fftChart) {
                fftChart.setSize({
                    width: fftChartElement.offsetWidth,
                    height: containerHeight
                });
            }
        }, 0);
    } catch (error) {
        console.error('Error creating FFT chart:', error);
    }
    
    // 창 크기 변경 시 차트 크기 조정
    const resizeHandler = () => {
        if (fftChart) {
            fftChart.setSize({
                width: fftChartElement.offsetWidth,
                height: containerHeight
            });
        }
    };
    
    window.addEventListener('resize', resizeHandler);
}

// 버튼 상태 업데이트 함수 수정
function updateButtonStates() {
    // 복수 차트 선택 시 Min/Max, FFT, Filter 비활성화
    if (selectedCharts.length > 1) {
        minmaxBtn.disabled = true;
        minmaxBtn.classList.add('disabled');
        fftBtn.disabled = true;
        fftBtn.classList.add('disabled');
        fftBtn.classList.remove('primary');
        filterBtn.disabled = true;
        filterBtn.classList.add('disabled');
        filterBtn.classList.remove('primary');
        
        // 여러 차트 선택 시 Scale 버튼 활성화
        scaleBtn.disabled = false;
        scaleBtn.classList.remove('disabled');
    }
    // FFT 버튼 상태 업데이트
    if (selectedChart && selectedCharts.length === 1) {
        const chart = charts.find(c => c.id === selectedChart);
        const hasSingleParameter = chart && chart.parameters.length === 1;
        const hasAnyParameter = chart && chart.parameters.length >= 1;
        // Scale, Min/Max, FFT, Filter 활성화 조건
        scaleBtn.disabled = !hasSingleParameter;
        minmaxBtn.disabled = !hasAnyParameter; // 수정: 1개 이상이면 활성화
        fftBtn.disabled = !hasSingleParameter;
        filterBtn.disabled = !hasSingleParameter;
        [scaleBtn, minmaxBtn].forEach(btn => {
            if ((btn === minmaxBtn && hasAnyParameter) || (btn !== minmaxBtn && hasSingleParameter)) btn.classList.remove('disabled');
            else btn.classList.add('disabled');
        });
        // FFT, Filter 버튼 스타일 통일
        if (hasSingleParameter) {
            fftBtn.classList.remove('disabled');
            fftBtn.classList.add('primary');
            filterBtn.classList.remove('disabled');
            filterBtn.classList.add('primary');
        } else {
            fftBtn.classList.add('disabled');
            fftBtn.classList.remove('primary');
            filterBtn.classList.add('disabled');
            filterBtn.classList.remove('primary');
        }
    } else if (selectedCharts.length === 0) {
        scaleBtn.disabled = true;
        minmaxBtn.disabled = true;
        fftBtn.disabled = true;
        filterBtn.disabled = true;
        [scaleBtn, minmaxBtn].forEach(btn => btn.classList.add('disabled'));
        fftBtn.classList.add('disabled');
        fftBtn.classList.remove('primary');
        filterBtn.classList.add('disabled');
        filterBtn.classList.remove('primary');
    }
    // Scatter 버튼 상태 업데이트
    if (selectedCharts.length === 2) {
        const chart1 = charts.find(c => c.id === selectedCharts[0]);
        const chart2 = charts.find(c => c.id === selectedCharts[1]);
        const bothHaveSingleParameter = chart1 && chart2 && 
                                      chart1.parameters.length === 1 && 
                                      chart2.parameters.length === 1;
        scatterBtn.disabled = !bothHaveSingleParameter;
        if (bothHaveSingleParameter) {
            scatterBtn.classList.remove('disabled');
            scatterBtn.classList.add('primary');
        } else {
            scatterBtn.classList.add('disabled');
            scatterBtn.classList.remove('primary');
        }
    } else {
        scatterBtn.disabled = true;
        scatterBtn.classList.add('disabled');
        scatterBtn.classList.remove('primary');
    }
    // Filter/Time Segment/Derived Para는 별도 처리
    // New Derived, Time Segment는 파일 업로드 시 활성화(업로드 콜백에서 처리)
    
    // Utility Apps 버튼 활성화 (파일이 업로드되면 항상 활성화)
    const utilityAppsBtn = document.getElementById('utility-apps-btn');
    if (utilityAppsBtn) {
        const hasData = charts.length > 0 || document.getElementById('parameters-list').children.length > 0;
        utilityAppsBtn.disabled = !hasData;
        if (hasData) {
            utilityAppsBtn.classList.remove('disabled');
        } else {
            utilityAppsBtn.classList.add('disabled');
        }
    }
}

// FFT 버튼 클릭 이벤트
fftBtn.addEventListener('click', () => {
    if (selectedChart) {
        performFFTAnalysis(selectedChart);
    }
});

// FFT 팝업 닫기 버튼 이벤트
document.querySelector('#fft-popup .close-btn').addEventListener('click', () => {
    fftPopup.style.display = 'none';
    if (fftChart) {
        fftChart.destroy();
        fftChart = null;
    }
});

// Tooltip plugin for uPlot
function tooltipPlugin() {
    return {
        hooks: {
            setCursor: [
                (u) => {
                    const { left, top } = u.cursor;
                    const tooltip = document.getElementById('tooltip');
                    
                    if (left === null || top === null) {
                        tooltip.style.display = 'none';
                        return;
                    }
                    
                    const x = u.cursor.idx;
                    if (x === null) return;
                    
                    const xVal = u.data[0][x];
                    const yVal = u.data[1][x];
                    
                    tooltip.innerHTML = `X: ${xVal.toFixed(2)}<br>Y: ${yVal.toFixed(2)}`;
                    tooltip.style.display = 'block';
                    tooltip.style.left = left + 'px';
                    tooltip.style.top = top + 'px';
                }
            ]
        }
    };
}

// Scatter 차트 생성 함수 수정
async function createScatterChart(chartId1, chartId2) {
    try {
        const chart1 = charts.find(c => c.id === chartId1);
        const chart2 = charts.find(c => c.id === chartId2);
        
        if (!chart1 || !chart2 || 
            chart1.parameters.length === 0 || 
            chart2.parameters.length === 0) {
            throw new Error('Invalid chart selection');
        }

        // 각 차트의 첫 번째 파라미터만 사용
        const param1 = chart1.parameters[0];
        const param2 = chart2.parameters[0];

        // 현재 보여지는 시간 영역대 가져오기
        const scale1 = chart1.plot.scales.x;
        const scale2 = chart2.plot.scales.x;
        const start = Math.max(scale1.min, scale2.min);
        const end = Math.min(scale1.max, scale2.max);

        // 데이터 요청
        const [data1, data2] = await Promise.all([
            fetchChartData(param1, start, end, 2000),
            fetchChartData(param2, start, end, 2000)
        ]);

        if (!data1.time || !data1.value || !data2.time || !data2.value) {
            throw new Error('Invalid data received from server');
        }

        const alignedY = alignSeries(new Float64Array(data1.time), data2.time, data2.value);
        const paired = data1.value.map((x, i) => [Number(x), alignedY[i]])
            .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
        if (paired.length < 2) throw new Error('Not enough overlapping finite samples');
        const xValues = paired.map(p => p[0]);
        const yValues = paired.map(p => p[1]);
        console.log('Creating scatter chart with data points:', paired.length);
        
        // 데이터가 너무 많은 경우 처리
        const maxPoints = 10000; // 최대 표시할 포인트 수
        let plotX, plotY;
        
        if (paired.length > maxPoints) {
            const step = Math.ceil(paired.length / maxPoints);
            plotX = [];
            plotY = [];
            for (let i = 0; i < paired.length; i += step) {
                plotX.push(xValues[i]);
                plotY.push(yValues[i]);
            }
        } else {
            plotX = xValues;
            plotY = yValues;
        }

        // 데이터 배열이 모두 같은 길이인지 확인
        if (plotX.length !== plotY.length) {
            throw new Error('Data arrays must have the same length');
        }

        // X축과 Y축의 최소/최대값 계산
        const xMin = Math.min(...plotX);
        const xMax = Math.max(...plotX);
        const yMin = Math.min(...plotY);
        const yMax = Math.max(...plotY);

        // 선형 회귀 계산 (전체 데이터 사용)
        const n = paired.length;
        const sumX = xValues.reduce((a, b) => a + b, 0);
        const sumY = yValues.reduce((a, b) => a + b, 0);
        const sumXY = xValues.reduce((sum, x, i) => sum + x * yValues[i], 0);
        const sumX2 = xValues.reduce((sum, x) => sum + x * x, 0);
        
        const denominator = n * sumX2 - sumX * sumX;
        if (Math.abs(denominator) < Number.EPSILON) throw new Error('X values have no variance');
        const slope = (n * sumXY - sumX * sumY) / denominator;
        const intercept = (sumY - slope * sumX) / n;
        
        // R² 계산
        const yMean = sumY / n;
        const ssTot = yValues.reduce((sum, y) => sum + Math.pow(y - yMean, 2), 0);
        const ssRes = yValues.reduce((sum, y, i) => sum + Math.pow(y - (slope * xValues[i] + intercept), 2), 0);
        const r2 = ssTot === 0 ? 1 : 1 - (ssRes / ssTot);

        // 회귀선 데이터 생성 (plotX의 각 값에 대해)
        const regressionY = plotX.map(x => slope * x + intercept);
        // plotX와 regressionY를 X 기준으로 정렬
        const zipped = plotX.map((x, i) => ({ x, y: plotY[i], reg: regressionY[i] }));
        zipped.sort((a, b) => a.x - b.x);

        const sortedX = zipped.map(p => p.x);
        const sortedY = zipped.map(p => p.y);
        const sortedRegressionY = zipped.map(p => p.reg);

        let scatterData = [
            new Float64Array(sortedX),
            new Float64Array(sortedY),
            new Float64Array(sortedRegressionY)
        ];

        // 차트 컨테이너 크기 확인
        const containerWidth = scatterChartElement.offsetWidth || 800;
        const containerHeight = 400;

        // uPlot 옵션 설정
        const opts = {
            width: containerWidth,
            height: containerHeight,
            title: `Scatter Plot: ${param1} vs ${param2}`,
            cursor: {
                show: true,
            },
            scales: {
                x: {
                    time: false,
                    auto: false,
                    min: xMin,
                    max: xMax,
                },
                y: {
                    auto: false,
                    min: yMin,
                    max: yMax,
                },
            },
            series: [
                {
                    label: param1,
                    value: (u, v) => v == null ? "-" : v.toFixed(2),
                },
                {
                    label: param2,
                    stroke: '#2196F3',
                    width: 1,
                    points: {
                        show: true,
                        size: 3,
                        fill: 'rgba(54, 162, 235, 0.5)',
                    },
                    value: (u, v) => v == null ? "-" : v.toFixed(2),
                },
                {
                    label: 'Regression',
                    stroke: '#FF5722',
                    width: 1,
                    points: { show: false },
                    value: (u, v) => v == null ? "-" : v.toFixed(2),
                }
            ],
            padding: [10, 10, 10, 10],
            axes: [
                {
                    stroke: '#000',
                    grid: { show: true },
                    ticks: { show: true },
                    size: 30,
                    label: param1,
                    labelSize: 20,
                    labelGap: 0,
                    labelOffset: 0,
                    labelFont: '12px Arial',
                },
                {
                    stroke: '#000',
                    grid: { show: true },
                    ticks: { show: true },
                    size: 30,
                    label: param2,
                    labelSize: 20,
                    labelGap: 0,
                    labelOffset: 0,
                    labelFont: '12px Arial',
                }
            ],
        };

        // 기존 차트 제거
        if (scatterChart) {
            scatterChart.destroy();
        }

        // stats div가 없으면 생성
        let statsDiv = document.getElementById('scatterStats');
        if (!statsDiv) {
            statsDiv = document.createElement('div');
            statsDiv.id = 'scatterStats';
            statsDiv.style.padding = '10px';
            statsDiv.style.backgroundColor = '#f5f5f5';
            statsDiv.style.borderRadius = '4px';
            statsDiv.style.marginTop = '10px';
            scatterChartElement.parentNode.insertBefore(statsDiv, scatterChartElement.nextSibling);
        }

        // 통계 정보 표시 (수식 포함)
        const equation = `y = ${slope.toFixed(6)}x + ${intercept.toFixed(6)}`;
        statsDiv.innerHTML = `
            <h4>Statistics</h4>
            <p>Number of points: ${data1.value.length}</p>
            <p>Regression equation: ${equation}</p>
            <p>R²: ${r2.toFixed(6)}</p>
        `;

        // 모든 데이터 배열이 유효한지 확인
        if (!scatterData.every(arr => arr instanceof Float64Array && arr.length > 0)) {
            throw new Error('Invalid data arrays');
        }

        // 새 차트 생성
        scatterChart = new uPlot(opts, scatterData, scatterChartElement);

        // 창 크기 변경 시 차트 크기 조정
        const resizeHandler = () => {
            if (scatterChart) {
                scatterChart.setSize({
                    width: scatterChartElement.offsetWidth,
                    height: containerHeight
                });
            }
        };
        
        window.addEventListener('resize', resizeHandler);

    } catch (error) {
        console.error('Error creating scatter chart:', error);
        throw error;
    }
}

// Scatter 버튼 클릭 이벤트 수정
scatterBtn.addEventListener('click', async () => {
    if (selectedCharts.length !== 2) {
        alert('Please select exactly two charts for scatter plot');
        return;
    }

    const chart1 = charts.find(c => c.id === selectedCharts[0]);
    const chart2 = charts.find(c => c.id === selectedCharts[1]);

    if (!chart1 || !chart2 || 
        chart1.parameters.length === 0 || 
        chart2.parameters.length === 0) {
        alert('Both charts must have at least one parameter');
        return;
    }

    try {
        // 기존 scatter 차트가 있다면 제거
        if (scatterChart) {
            scatterChart.destroy();
            scatterChart = null;
        }
        
        // scatter 팝업이 닫혀있다면 열기
        if (scatterPopup.style.display !== 'flex') {
            scatterPopup.style.display = 'flex';
        }
        
        await createScatterChart(selectedCharts[0], selectedCharts[1]);
    } catch (error) {
        console.error('Error in scatter button click:', error);
        alert('Error creating scatter chart: ' + error.message);
        // 에러 발생 시 팝업 닫기
        scatterPopup.style.display = 'none';
    }
});

// Scatter 팝업 닫기 버튼 이벤트
scatterPopup.querySelector('.close-btn').addEventListener('click', () => {
    scatterPopup.style.display = 'none';
    if (scatterChart) {
        scatterChart.destroy();
        scatterChart = null;
    }
});

// Show filter form based on selected filter type
document.querySelectorAll('.dropdown-content a').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        currentFilterType = e.target.dataset.filter;
        
        // Hide all filter forms
        document.querySelectorAll('.filter-form-content').forEach(form => {
            form.style.display = 'none';
        });
        
        // Show selected filter form
        document.getElementById(`${currentFilterType}-form`).style.display = 'block';
        
        // Show filter popup
        filterPopup.style.display = 'flex';
    });
});

// Apply filter button click handler
document.getElementById('apply-filter').addEventListener('click', async () => {
    if (!selectedChart || !currentFilterType) return;
    
    const chart = charts.find(c => c.id === selectedChart);
    if (!chart || chart.parameters.length !== 1) return;
    
    try {
        // Get filter parameters
        const params = {};
        let filterTitle = '';
        
        if (currentFilterType === 'lpf') {
            const cutoffFreq = parseFloat(document.getElementById('lpf-cutoff').value);
            const order = parseInt(document.getElementById('lpf-order').value);
            
            if (isNaN(cutoffFreq) || isNaN(order)) {
                throw new Error('Invalid filter parameters');
            }
            
            // 정규화 없이 실제 Hz 값만 전달
            params.cutoff_freq = cutoffFreq;
            params.order = order;
            filterTitle = `_LPF_${cutoffFreq}Hz_${order}order`;
        } else if (currentFilterType === 'bpf') {
            const lowFreq = parseFloat(document.getElementById('bpf-low').value);
            const highFreq = parseFloat(document.getElementById('bpf-high').value);
            const order = parseInt(document.getElementById('bpf-order').value);
            
            if (isNaN(lowFreq) || isNaN(highFreq) || isNaN(order)) {
                throw new Error('Invalid filter parameters');
            }
            
            params.low_freq = lowFreq;
            params.high_freq = highFreq;
            params.order = order;
            filterTitle = `_BPF_${lowFreq}_${highFreq}Hz_${order}order`;
        } else if (currentFilterType === 'ma') {
            const windowSize = parseInt(document.getElementById('ma-window').value);
            if (isNaN(windowSize) || windowSize <= 0) {
                throw new Error('Invalid window size');
            }
            params.window_size = windowSize;
            filterTitle = `_MA_${windowSize}window`;
        } else if (currentFilterType === 'rms') {
            const windowSize = parseInt(document.getElementById('rms-window').value);
            if (isNaN(windowSize) || windowSize <= 0) {
                throw new Error('Invalid window size');
            }
            params.window_size = windowSize;
            filterTitle = `_RMS_${windowSize}window`;
        }
        
        const result = await runBackgroundJob('filter', {
            parameter: chart.parameters[0],
            filter_type: currentFilterType,
            params: params
        });
        
        if (result) {
            // Update chart title with filter information
            const chartContainer = document.getElementById(selectedChart);
            const titleElement = chartContainer.querySelector('.chart-title');
            titleElement.textContent = `${chart.parameters[0]}${filterTitle}`;
            
            // Update existing chart with filtered data
            await updateChart(selectedChart, result.parameter);
            
            // Show filter info
            const filterInfo = result.filter_info;
            filterInfoText.innerHTML = `
                <div class="filter-info-section">
                    <h4>필터 수식</h4>
                    <pre>${filterInfo.formula}</pre>
                </div>
                <div class="filter-info-section">
                    <h4>필터 정보</h4>
                    <pre>${filterInfo.description}</pre>
                </div>`;
            
            // Create frequency response charts
            if (filterInfo.frequency_response) {
                const { freq, magnitude } = filterInfo.frequency_response;
                
                // Magnitude response chart
                const magnitudeOpts = {
                    width: 300,
                    height: 220,
                    title: '',
                    cursor: { show: true },
                    scales: {
                        x: {
                            time: false,
                            label: '주파수 (Hz)',
                            auto: true,
                        },
                        y: {
                            label: '크기 (dB)',
                            auto: true,
                        }
                    },
                    series: [
                        {},
                        {
                            label: '크기',
                            stroke: '#2196F3',
                            width: 1,
                        }
                    ],
                    axes: [
                        {
                            stroke: '#000',
                            grid: { show: true },
                            ticks: { show: true },
                            size: 30,
                        },
                        {
                            stroke: '#000',
                            grid: { show: true },
                            ticks: { show: true },
                            size: 30,
                        }
                    ]
                };
                
                // Clean up existing charts
                if (window.filterCharts) {
                    window.filterCharts.forEach(chart => chart.destroy());
                }
                
                // Create new chart
                const magnitudeChart = new uPlot(magnitudeOpts, [freq, magnitude], document.getElementById('magnitude-chart'));
                
                // Store chart instance
                window.filterCharts = [magnitudeChart];
                
                // Remove resize handler since we're using fixed size
                if (window.filterCharts) {
                    window.removeEventListener('resize', window.filterCharts.resizeHandler);
                }
            }
            
            filterInfoPopup.style.display = 'flex';
            
            // Close filter popup
            filterPopup.style.display = 'none';

            // 파라미터 리스트 업데이트
            if (typeof loadParameters === 'function') {
                await loadParameters();
            }
        }
    } catch (error) {
        console.error('Error applying filter:', error);
        alert('Error applying filter: ' + error.message);
    }
});

// Close filter info popup
filterInfoPopup.querySelector('.close-btn').addEventListener('click', () => {
    filterInfoPopup.style.display = 'none';
    // Clean up charts
    if (window.filterCharts) {
        window.filterCharts.forEach(chart => chart.destroy());
        window.filterCharts = null;
    }
});

// Min/Max 분석 함수
async function performMinMaxAnalysis(chartId) {
    const chart = charts.find(c => c.id === chartId);
    if (!chart || chart.parameters.length === 0) return;

    try {
        // 현재 보여지는 시간 영역대 가져오기
        const currentScale = chart.plot.scales.x;
        const start = currentScale.min;
        const end = currentScale.max;

        // Exact statistics are computed chunk-wise on the server; no
        // downsampling can hide a narrow spike.
        const responses = await Promise.all(chart.parameters.map(async parameter => {
            const response = await fetch(`/api/statistics?parameter=${encodeURIComponent(parameter)}&start=${start}&end=${end}`);
            const body = await response.json();
            if (!response.ok) throw new Error(body.error || 'Statistics request failed');
            return { parameter, ...body };
        }));
        const results = responses.filter(r => r.valid_count > 0).map(r => ({
            parameter: r.parameter, minValue: r.min, maxValue: r.max,
            minTime: r.min_time, maxTime: r.max_time, dataPoints: r.count
        }));

        // 결과 표시
        const timeRangeStr = `${(end - start).toFixed(2)} seconds`;
        const resultsHtml = results.map(result => `
            <div class="parameter-section">
                <div class="parameter-name">${result.parameter}</div>
                <div class="value-row">
                    <span class="value-label">Min Value:</span>
                    <span class="value-data">${result.minValue.toFixed(6)}</span>
                </div>
                <div class="value-row">
                    <span class="value-label">Min Time:</span>
                    <span class="value-data">${result.minTime.toFixed(2)}s</span>
                </div>
                <div class="value-row">
                    <span class="value-label">Max Value:</span>
                    <span class="value-data">${result.maxValue.toFixed(6)}</span>
                </div>
                <div class="value-row">
                    <span class="value-label">Max Time:</span>
                    <span class="value-data">${result.maxTime.toFixed(2)}s</span>
                </div>
                <div class="time-info">
                    Time Range: ${timeRangeStr} | Data Points: ${result.dataPoints.toLocaleString()}
                </div>
            </div>
        `).join('');

        minmaxInfoText.innerHTML = resultsHtml;
        
        // 팝업 표시
        minmaxPopup.style.display = 'flex';
    } catch (error) {
        console.error('Error performing Min/Max analysis:', error);
        alert('Error performing Min/Max analysis: ' + error.message);
    }
}

// Min/Max 버튼 클릭 이벤트
minmaxBtn.addEventListener('click', () => {
    if (selectedChart) {
        performMinMaxAnalysis(selectedChart);
    }
});

// Min/Max 팝업 닫기 버튼 이벤트
minmaxPopup.querySelector('.close-btn').addEventListener('click', () => {
    minmaxPopup.style.display = 'none';
});

// 화면 캡처 함수 구현
async function capturePlotArea() {
    try {
        // plot-area 요소 가져오기
        const plotArea = document.getElementById('plot-area');
        if (!plotArea) {
            throw new Error('Plot area not found');
        }

        // html2canvas를 사용하여 캡처
        const canvas = await html2canvas(plotArea, {
            scale: 2, // 고해상도 캡처
            useCORS: true, // 외부 리소스 허용
            logging: false, // 로깅 비활성화
            backgroundColor: '#ffffff' // 배경색 설정
        });

        // 캡처된 이미지를 다운로드
        const link = document.createElement('a');
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        link.download = `wavelab-capture-${timestamp}.png`;
        link.href = canvas.toDataURL('image/png');
        link.click();

        // 메모리 정리
        canvas.remove();
        link.remove();
    } catch (error) {
        console.error('Error capturing plot area:', error);
        alert('Error capturing plot area: ' + error.message);
    }
}

// Scale dialog HTML
const scaleDialogHTML = `
<div id="scaleDialog" class="modal">
    <div class="modal-content">
        <div class="modal-header">
            <h2>Scale Settings</h2>
            <span class="close">&times;</span>
        </div>
        <div class="modal-body">
            <div class="scale-section">
                <h3>X-Axis Scale (Common for All Charts)</h3>
                <div class="input-group">
                    <label>Min:</label>
                    <input type="number" id="xMin" step="any">
                </div>
                <div class="input-group">
                    <label>Max:</label>
                    <input type="number" id="xMax" step="any">
                </div>
            </div>
            <div class="scale-section">
                <h3>Y-Axis Scale (Selected Charts Only)</h3>
                <div class="input-group">
                    <label>Min:</label>
                    <input type="number" id="yMin" step="any">
                </div>
                <div class="input-group">
                    <label>Max:</label>
                    <input type="number" id="yMax" step="any">
                </div>
            </div>
        </div>
        <div class="modal-footer">
            <button id="applyScale" class="btn btn-primary">Apply</button>
            <button id="cancelScale" class="btn btn-secondary">Cancel</button>
        </div>
    </div>
</div>
`;

// Add scale dialog to the document
document.body.insertAdjacentHTML('beforeend', scaleDialogHTML);

// Scale dialog elements
const scaleDialog = document.getElementById('scaleDialog');
const closeScaleBtn = scaleDialog?.querySelector('.close');
const cancelScaleBtn = document.getElementById('cancelScale');
const applyScaleBtn = document.getElementById('applyScale');
const xMinInput = document.getElementById('xMin');
const xMaxInput = document.getElementById('xMax');
const yMinInput = document.getElementById('yMin');
const yMaxInput = document.getElementById('yMax');

// Show scale dialog
scaleBtn?.addEventListener('click', () => {
    const selectedCharts = document.querySelectorAll('.chart-container.selected');
    if (selectedCharts.length === 0) {
        alert('Please select at least one chart for Y-axis scale');
        return;
    }

    // Get current scales from the first selected chart
    const firstChart = charts.find(c => c.id === selectedCharts[0].id);
    if (firstChart && firstChart.plot) {
        const scales = firstChart.plot.scales;
        xMinInput.value = scales.x.min;
        xMaxInput.value = scales.x.max;
        yMinInput.value = scales.y.min;
        yMaxInput.value = scales.y.max;
    }

    // Update dialog title to show number of selected charts
    const dialogTitle = scaleDialog.querySelector('.modal-header h2');
    if (selectedCharts.length === 1) {
        dialogTitle.textContent = 'Scale Settings (1 Chart Selected for Y-axis)';
    } else {
        dialogTitle.textContent = `Scale Settings (${selectedCharts.length} Charts Selected for Y-axis)`;
    }

    scaleDialog.style.display = 'block';
});

// Close scale dialog
closeScaleBtn?.addEventListener('click', () => {
    scaleDialog.style.display = 'none';
    // Reset dialog title
    const dialogTitle = scaleDialog.querySelector('.modal-header h2');
    dialogTitle.textContent = 'Scale Settings';
});

cancelScaleBtn?.addEventListener('click', () => {
    scaleDialog.style.display = 'none';
    // Reset dialog title
    const dialogTitle = scaleDialog.querySelector('.modal-header h2');
    dialogTitle.textContent = 'Scale Settings';
});

// Apply scale changes
applyScaleBtn?.addEventListener('click', () => {
    const xMin = parseFloat(xMinInput.value);
    const xMax = parseFloat(xMaxInput.value);
    const yMin = parseFloat(yMinInput.value);
    const yMax = parseFloat(yMaxInput.value);

    if (isNaN(xMin) || isNaN(xMax) || isNaN(yMin) || isNaN(yMax)) {
        alert('Please enter valid numbers for all scale values');
        return;
    }

    if (xMin >= xMax || yMin >= yMax) {
        alert('Min values must be less than Max values');
        return;
    }

    // Apply X scale to ALL charts (common X-axis scale)
    charts.forEach(chart => {
        if (chart && chart.plot) {
            chart.plot.setScale('x', { min: xMin, max: xMax });
        }
    });

    // Apply Y scale only to selected charts
    const selectedCharts = document.querySelectorAll('.chart-container.selected');
    selectedCharts.forEach(container => {
        const chart = charts.find(c => c.id === container.id);
        if (chart && chart.plot) {
            chart.plot.setScale('y', { min: yMin, max: yMax });
        }
    });

    scaleDialog.style.display = 'none';
});

// Global Time 표시 함수
function formatGlobalTime(seconds) {
    if (!isFinite(seconds) || seconds <= 0) return '--';
    const date = new Date(seconds * 1000);
    // 연도 첫날 기준 DDD 계산
    const year = date.getUTCFullYear();
    const startOfYear = new Date(Date.UTC(year, 0, 1));
    const diff = date - startOfYear;
    const ddd = Math.floor(diff / (1000 * 60 * 60 * 24)) + 1;
    const hh = String(date.getUTCHours()).padStart(2, '0');
    const mm = String(date.getUTCMinutes()).padStart(2, '0');
    const ss = String(date.getUTCSeconds()).padStart(2, '0');
    return `${ddd} ${hh}:${mm}:${ss}`;
}

async function updateGlobalTimeInfo() {
    try {
        const resp = await fetch('/api/global_time');
        if (!resp.ok) throw new Error('Failed to fetch global time');
        const data = await resp.json();
        console.log('Fetched global time:', data); // 진단용 로그
        const startStr = formatGlobalTime(data.start);
        const endStr = formatGlobalTime(data.end);
        document.getElementById('global-time-info').textContent = `GLOBAL TIME · ${startStr} — ${endStr}`;
    } catch (e) {
        document.getElementById('global-time-info').textContent = 'GLOBAL TIME · --';
        console.error('Global time fetch error:', e); // 진단용 로그
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const policySelect = document.getElementById('alignment-policy');
    if (policySelect) {
        policySelect.value = alignmentPolicy;
        policySelect.addEventListener('change', () => {
            alignmentPolicy = policySelect.value;
            localStorage.setItem('wavelab-alignment-policy', alignmentPolicy);
            charts.forEach(chart => {
                if (chart.parameters?.length && chart.plot?.scales?.x) {
                    updateChartData(chart.id, chart.parameters,
                                    chart.plot.scales.x.min, chart.plot.scales.x.max);
                }
            });
        });
    }
    const qualityPopup = document.getElementById('quality-popup');
    document.getElementById('quality-btn')?.addEventListener('click', () => {
        showChannelQuality().catch(error => showNotification(error.message, 'error'));
    });
    qualityPopup?.querySelector('.close-btn')?.addEventListener('click', () => {
        qualityPopup.style.display = 'none';
    });
});

// Initialize
loadParameters();

document.addEventListener('DOMContentLoaded', function() {
    // Patch generateBtn click event safely
    const generateBtn = document.getElementById('generate-parameter');
    if (generateBtn) {
        generateBtn.addEventListener('click', async function() {
            const parameterName = document.getElementById('parameter-name').value.trim();
            if (!parameterName) {
                alert('Please enter a parameter name');
                return;
            }
            const code = window.monacoEditor.getValue();
            if (!code) {
                alert('Please enter some code');
                return;
            }
            // Get available parameters from the list
            const paramItems = document.querySelectorAll('.parameter-item');
            const availableParams = Array.from(paramItems).map(x => x.textContent.trim());
            const usedParams = extractParameterNamesFromCode(code, availableParams);
            if (usedParams.length === 0) {
                alert('코드에서 사용할 파라미터를 입력하세요. (파라미터명을 클릭하면 자동 입력됩니다)');
                return;
            }
            try {
                const data = await runBackgroundJob('derived', {
                    name: parameterName,
                    code: code,
                    parameters: usedParams,
                    alignment: alignmentPolicy
                });
                if (data) {
                    alert('Parameter generated successfully');
                    document.getElementById('derived-panel').classList.remove('visible');
                    document.getElementById('derived-panel').style.width = '600px'; // 패널 너비 복원
                    if (typeof loadParameters === 'function') loadParameters();
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        });
    }
    
    // 모바일 체크 함수
    function isMobile() {
        return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    }

    // 모바일인 경우 업로드 버튼 비활성화
    const uploadBtn = document.getElementById('upload-btn');
    if (uploadBtn && isMobile()) {
        uploadBtn.style.display = 'none';
    }

    // Save database button handler
    const saveDbBtn = document.getElementById('save-db-btn');
    if (saveDbBtn) {
        saveDbBtn.addEventListener('click', async function() {
            const fileName = prompt('저장할 DB 파일명을 입력하세요 (예: mydata.db):');
            if (!fileName) return;
            if (!fileName.endsWith('.db')) {
                alert('파일명은 .db 확장자로 끝나야 합니다.');
                return;
            }
            try {
                // 현재 차트 정보 수집
                const chartsInfo = collectChartInfo();
                console.log('Saving chart info:', chartsInfo);
                
                const response = await fetch('/api/save_database', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        file_name: fileName,
                        charts_info: chartsInfo
                    })
                });
                const data = await response.json();
                if (response.ok) {
                    alert(`DB가 성공적으로 저장되었습니다!\n경로: ${data.path}\n차트 정보: ${chartsInfo.length}개 차트`);
                } else {
                    alert('오류: ' + data.error);
                }
            } catch (error) {
                alert('DB 저장 중 오류: ' + error.message);
            }
        });
    }

    // Restore database button handler
    const restoreDbBtn = document.getElementById('restore-db-btn');
    if (restoreDbBtn) {
        restoreDbBtn.addEventListener('click', async function() {
            if (!confirm('백업에서 데이터베이스를 복원하시겠습니까? 현재 데이터베이스는 덮어쓰여집니다.')) {
                return;
            }
            try {
                const response = await fetch('/api/restore_database', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await response.json();
                if (response.ok) {
                    alert('데이터베이스가 성공적으로 복원되었습니다!');
                    // 파라미터 목록 갱신
                    if (typeof loadParameters === 'function') loadParameters();
                    // 글로벌 타임 갱신
                    if (typeof updateGlobalTimeInfo === 'function') updateGlobalTimeInfo();
                    // File 탭으로 전환
                    document.querySelector('[data-tab="file"]').click();
                } else {
                    alert('오류: ' + data.error);
                }
            } catch (error) {
                alert('DB 복원 중 오류: ' + error.message);
            }
        });
    }
    
    // File 탭을 명시적으로 클릭하여 초기 상태 확실히 설정
    setTimeout(() => {
        const fileTab = document.querySelector('[data-tab="file"]');
        if (fileTab) {
            fileTab.click();
        }
    }, 100);
    
    // BIT Extractor 닫기 버튼 이벤트 리스너 설정
    const bitExtractorCloseBtn = document.querySelector('#bit-extractor-popup .close-btn');
    if (bitExtractorCloseBtn) {
        bitExtractorCloseBtn.addEventListener('click', () => {
            document.getElementById('bit-extractor-popup').style.display = 'none';
            // 버튼 상태 초기화
            const generateBtn = document.getElementById('generate-bit-extractor-btn');
            if (generateBtn) {
                generateBtn.disabled = false;
                generateBtn.textContent = 'Generate';
                generateBtn.classList.remove('processing');
            }
        });
    }

    // Notepad functionality
    const generalNotesTextarea = document.getElementById('general-notes-textarea');
    const sessionNotesTextarea = document.getElementById('session-notes-textarea');

    // --- General Note (localStorage) ---
    if(generalNotesTextarea) {
        generalNotesTextarea.value = localStorage.getItem('wavelab_general_notes') || '';

        let generalNoteTimer;
        generalNotesTextarea.addEventListener('input', () => {
            clearTimeout(generalNoteTimer);
            generalNoteTimer = setTimeout(() => {
                localStorage.setItem('wavelab_general_notes', generalNotesTextarea.value);
                showNotification('General note saved.');
            }, 2000);
        });
    }

    // --- Session Notes (Database) ---
    window.loadSessionNotes = function() {
        if (!sessionNotesTextarea) return;
        fetch('/api/session_notes')
            .then(response => response.json())
            .then(data => {
                if (data.success && data.notes) {
                    sessionNotesTextarea.value = data.notes;
                } else {
                    sessionNotesTextarea.value = '';
                }
            })
            .catch(error => {
                console.error('Error loading session notes:', error);
                sessionNotesTextarea.value = '';
            });
    }

    function saveSessionNotes() {
        if (!sessionNotesTextarea) return;
        const content = sessionNotesTextarea.value;
        fetch('/api/session_notes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes: content })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                console.log('Session notes saved.');
            }
        })
        .catch(error => console.error('Error saving session notes:', error));
    }

    if (sessionNotesTextarea) {
        loadSessionNotes();

        let sessionNoteTimer;
        sessionNotesTextarea.addEventListener('input', () => {
            clearTimeout(sessionNoteTimer);
            sessionNoteTimer = setTimeout(saveSessionNotes, 3000);
        });
    }
    
    // Default tab state
    const fileTab = document.querySelector('[data-tab="file"]');
    if (fileTab) {
        fileTab.click();
    }
});

// --- ALT key shortcut badge logic ---
const addChartBadge = addChartBtn.querySelector('.shortcut-badge');
const scaleBadge = scaleBtn.querySelector('.shortcut-badge');
const minmaxBadge = minmaxBtn.querySelector('.shortcut-badge');
const fftBadge = fftBtn.querySelector('.shortcut-badge');
const scatterBadge = scatterBtn.querySelector('.shortcut-badge');

let altKeyDown = false;
window.addEventListener('keydown', (e) => {
    if (e.altKey && !altKeyDown) {
        altKeyDown = true;
        addChartBadge.style.display = 'inline-block';
        scaleBadge.style.display = 'inline-block';
        minmaxBadge.style.display = 'inline-block';
        fftBadge.style.display = 'inline-block';
        scatterBadge.style.display = 'inline-block';
    }
    // 단축키 기능
    if (e.altKey && !e.repeat) {
        switch (e.key) {
            case '1':
                e.preventDefault();
                addChartBtn.click();
                break;
            case '2':
                e.preventDefault();
                scaleBtn.click();
                break;
            case '3':
                e.preventDefault();
                minmaxBtn.click();
                break;
            case '4':
                e.preventDefault();
                fftBtn.click();
                break;
            case '5':
                e.preventDefault();
                scatterBtn.click();
                break;
        }
    }
});
window.addEventListener('keyup', (e) => {
    if (!e.altKey && altKeyDown) {
        altKeyDown = false;
        addChartBadge.style.display = 'none';
        scaleBadge.style.display = 'none';
        minmaxBadge.style.display = 'none';
        fftBadge.style.display = 'none';
        scatterBadge.style.display = 'none';
    }
});

// 파라미터 이름 추출 함수
function extractParameterNamesFromCode(code, availableParams) {
    // 코드에서 사용된 파라미터 이름 추출
    const usedParams = [];
    for (const param of availableParams) {
        if (code.includes(param)) {
            usedParams.push(param);
        }
    }
    return usedParams;
}

// Add close handler for filter popup
filterPopup.querySelector('.close-btn').addEventListener('click', () => {
    filterPopup.style.display = 'none';
});

// Time segment 캐시 초기화 함수
function clearTimeSegmentCache() {
    // Time segment 팝업이 열려있다면 닫기
    const timeSegmentPopup = document.getElementById('time-segment-popup');
    if (timeSegmentPopup) {
        timeSegmentPopup.style.display = 'none';
        // 팝업 내용 초기화
        const form = document.getElementById('time-segment-form');
        if (form) {
            form.style.display = '';
            form.reset();
        }
        // 팝업 타이틀 원복
        const title = timeSegmentPopup.querySelector('.popup-header h3');
        if (title) {
            title.textContent = 'Set segment';
        }
        // 세그먼트 목록 제거
        const listDiv = timeSegmentPopup.querySelector('.segment-list');
        if (listDiv) {
            listDiv.remove();
        }
    }
    console.log('Time segment cache cleared');
}

// BIT Extractor Popup logic
function showBitExtractorPopup() {
    const popup = document.getElementById('bit-extractor-popup');
    const paramListDiv = document.getElementById('bit-parameter-selection-list');
    const lsbInput = document.getElementById('bit-lsb');
    const msbInput = document.getElementById('bit-msb');
    const signInput = document.getElementById('bit-sign');
    const lsbScaleInput = document.getElementById('bit-lsb-scale');
    const formatRadios = document.getElementsByName('bit-data-format');
    const paramNameInput = document.getElementById('bit-parameter-name');
    let autoName = true;
    // Load parameters (single selection)
    fetch('/api/parameters')
        .then(res => res.json())
        .then(parameters => {
            if (!Array.isArray(parameters) || parameters.length === 0) {
                paramListDiv.innerHTML = '<div style="color:#888">No parameters available.</div>';
                return;
            }
            paramListDiv.innerHTML = parameters.map(param => `
                <div class="parameter-selection-item">
                    <input type="radio" name="bit-param-radio" id="bit-param-${param}" value="${param}">
                    <label for="bit-param-${param}">${param}</label>
                </div>
            `).join('');
            // 자동 이름 생성 이벤트
            function updateAutoName() {
                if (!autoName) return;
                const paramRadio = document.querySelector('input[name="bit-param-radio"]:checked');
                const lsb = lsbInput.value;
                const msb = msbInput.value;
                if (paramRadio && lsb !== '' && msb !== '') {
                    // LSB와 MSB의 순서에 관계없이 항상 작은 값부터 큰 값 순으로 표시
                    const minBit = Math.min(parseInt(lsb), parseInt(msb));
                    const maxBit = Math.max(parseInt(lsb), parseInt(msb));
                    const direction = parseInt(lsb) > parseInt(msb) ? '_rev' : '';
                    paramNameInput.value = `${paramRadio.value}_bit${minBit}_${maxBit}${direction}`;
                } else {
                    paramNameInput.value = '';
                }
            }
            // 파라미터 선택 시 자동 이름
            paramListDiv.querySelectorAll('input[name="bit-param-radio"]').forEach(radio => {
                radio.addEventListener('change', () => {
                    autoName = true;
                    updateAutoName();
                });
            });
            // LSB/MSB 입력 시 자동 이름
            lsbInput.addEventListener('input', () => { autoName = true; updateAutoName(); });
            msbInput.addEventListener('input', () => { autoName = true; updateAutoName(); });
            // 사용자가 직접 이름 입력 시 자동 이름 해제
            paramNameInput.addEventListener('input', function() {
                if (this.value !== '' && this !== document.activeElement) return;
                autoName = false;
            });
            // 팝업 열 때 자동 이름 초기화
            autoName = true;
            updateAutoName();
        });
    // Format radio: adjust bit index range
    function updateBitIndexRange() {
        const format = Array.from(formatRadios).find(r=>r.checked).value;
        let min = 0, max = (format === '32bit') ? 31 : 15;
        lsbInput.min = msbInput.min = signInput.min = min;
        lsbInput.max = msbInput.max = signInput.max = max;
        if (parseInt(lsbInput.value) > max) lsbInput.value = min;
        if (parseInt(msbInput.value) > max) msbInput.value = min;
        if (parseInt(signInput.value) > max) signInput.value = '';
        document.getElementById('bit-index-hint').textContent = `(0~${max} for ${format})`;
    }
    formatRadios.forEach(radio => {
        radio.addEventListener('change', updateBitIndexRange);
    });
    updateBitIndexRange();
    // Cancel button
    document.getElementById('cancel-bit-extractor-btn').onclick = () => {
        const generateBtn = document.getElementById('generate-bit-extractor-btn');
        generateBtn.disabled = false;
        generateBtn.textContent = 'Generate';
        generateBtn.classList.remove('processing');
        popup.style.display = 'none';
    };
    // Close button
    popup.querySelector('.close-btn').onclick = () => {
        const generateBtn = document.getElementById('generate-bit-extractor-btn');
        generateBtn.disabled = false;
        generateBtn.textContent = 'Generate';
        generateBtn.classList.remove('processing');
        popup.style.display = 'none';
    };
    // Generate button
    document.getElementById('generate-bit-extractor-btn').onclick = () => {
        const param = document.querySelector('input[name="bit-param-radio"]:checked');
        const format = Array.from(formatRadios).find(r=>r.checked).value;
        let lsb = parseInt(lsbInput.value);
        let msb = parseInt(msbInput.value);
        let signBit = signInput.value === '' ? null : parseInt(signInput.value);
        let lsbScale = parseFloat(lsbScaleInput.value);
        const newName = paramNameInput.value.trim();
        let min = 0, max = (format === '32bit') ? 31 : 15;
        
        if (!param) { alert('파라미터를 선택하세요.'); return; }
        if (!newName) { alert('새 파라미터 이름을 입력하세요.'); return; }
        if (isNaN(lsb) || isNaN(msb) || lsb < min || msb < min || lsb > max || msb > max) {
            alert(`LSB/MSB를 올바르게 입력하세요. (${min}~${max})`); return;
        }
        if (signBit !== null && (isNaN(signBit) || signBit < min || signBit > max)) {
            alert(`Sign Bit을 올바르게 입력하세요. (${min}~${max} 또는 비워두기)`); return;
        }
        if (isNaN(lsbScale) || lsbScale === 0) {
            alert('LSB Scale을 올바르게 입력하세요. (0이 아닌 실수)'); return;
        }
        
        // LSB Scale이 정수형태로 입력된 경우 Float 형태로 변환
        if (Number.isInteger(lsbScale)) {
            lsbScale = lsbScale + 0.0;
        }
        
        // 16bit format인 경우 인덱스 변환 (15 - 입력값)
        if (format === '16bit') {
            lsb = 15 - lsb;
            msb = 15 - msb;
            if (signBit !== null) {
                signBit = 15 - signBit;
            }
        }
        
        // Generate 버튼을 Processing... 상태로 변경하고 점멸 애니메이션 적용
        const generateBtn = document.getElementById('generate-bit-extractor-btn');
        generateBtn.disabled = true;
        generateBtn.textContent = 'Processing...';
        generateBtn.classList.add('processing');
        
        // 실제 구현 시 fetch로 backend 호출
        fetch('/api/bit_extractor', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_parameter: param.value,
                lsb: lsb,
                msb: msb,
                data_format: format,
                sign_bit_index: signBit,
                lsb_scale: lsbScale,
                parameter_name: newName
            })
        })
        .then(res => res.json())
        .then(result => {
            if (result.success) {
                // 완료 시 버튼 상태 복원
                generateBtn.disabled = false;
                generateBtn.textContent = 'Generate';
                generateBtn.classList.remove('processing');
                
                setTimeout(() => {
                    alert(`파라미터 생성 완료: ${result.parameter_name}`);
                    popup.style.display = 'none';
                    // 파라미터 목록 갱신
                    loadParameters();
                }, 500);
            } else {
                alert(result.error || '파라미터 생성 실패');
                // 에러 시 버튼 상태 복원
                generateBtn.disabled = false;
                generateBtn.textContent = 'Generate';
                generateBtn.classList.remove('processing');
            }
        })
        .catch(err => {
            alert('파라미터 생성 중 오류 발생');
            console.error(err);
            // 에러 시 버튼 상태 복원
            generateBtn.disabled = false;
            generateBtn.textContent = 'Generate';
            generateBtn.classList.remove('processing');
        });
    };
    // Show popup
    popup.style.display = 'flex';
}


// 드래그 앤 드롭 관련 변수

function handleDragStart(e) {
    if (!e.shiftKey) {
        e.preventDefault();
        return;
    }
    draggedChartId = this.id;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
}

function handleDragOver(e) {
    if (!e.shiftKey) return;
    e.preventDefault();
    this.classList.add('drag-over');
    e.dataTransfer.dropEffect = 'move';
}

function handleDrop(e) {
    if (!e.shiftKey) return;
    e.preventDefault();
    this.classList.remove('drag-over');
    if (draggedChartId && draggedChartId !== this.id) {
        const fromIdx = charts.findIndex(c => c.id === draggedChartId);
        const toIdx = charts.findIndex(c => c.id === this.id);
        if (fromIdx !== -1 && toIdx !== -1 && fromIdx !== toIdx) {
            const [moved] = charts.splice(fromIdx, 1);
            charts.splice(toIdx, 0, moved);
            updateGridLayout();
        }
    }
    draggedChartId = null;
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
}

// Configuration dropdown event handling
document.addEventListener('DOMContentLoaded', function() {
    const configDropdown = document.querySelector('.config-dropdown');
    if (configDropdown) {
        const dropdownContent = configDropdown.querySelector('.dropdown-content');
        
        // Configuration dropdown menu items click handling
        dropdownContent.addEventListener('click', function(e) {
            e.preventDefault();
            const configType = e.target.getAttribute('data-config');
            
            switch(configType) {
                case 'save':
                    alert('Configuration Save 기능이 호출되었습니다.');
                    // TODO: Configuration 저장 기능 구현
                    break;
                case 'import':
                    importConfigFromCSV();
                    break;
                case 'export':
                    exportConfigToCSV();
                    break;
                case 'change':
                    alert('Configuration Change 기능이 호출되었습니다.');
                    // TODO: Configuration 변경 기능 구현
                    break;
                default:
                    console.log('Unknown configuration type:', configType);
            }
        });
        
        // Hide dropdown when clicking outside
        document.addEventListener('click', function(e) {
            if (!configDropdown.contains(e.target)) {
                dropdownContent.style.display = 'none';
            }
        });
        
        // Show dropdown on button click
        const configBtn = configDropdown.querySelector('#config-btn');
        configBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropdownContent.style.display = dropdownContent.style.display === 'block' ? 'none' : 'block';
        });
    }
    
    // BIT Extractor 닫기 버튼 이벤트 리스너 설정
    const bitExtractorCloseBtn = document.querySelector('#bit-extractor-popup .close-btn');
    if (bitExtractorCloseBtn) {
        bitExtractorCloseBtn.addEventListener('click', () => {
            document.getElementById('bit-extractor-popup').style.display = 'none';
            // 버튼 상태 초기화
            const generateBtn = document.getElementById('generate-bit-extractor-btn');
            if (generateBtn) {
                generateBtn.disabled = false;
                generateBtn.textContent = 'Generate';
                generateBtn.classList.remove('processing');
            }
        });
    }
});

// Notification function
function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    notification.textContent = message;
    notification.style.position = 'fixed';
    notification.style.bottom = '20px';
    notification.style.left = '50%';
    notification.style.transform = 'translateX(-50%)';
    notification.style.padding = '10px 20px';
    notification.style.borderRadius = '5px';
    notification.style.color = 'white';
    notification.style.zIndex = '3000';
    notification.style.backgroundColor = type === 'success' ? 'rgba(40, 167, 69, 0.9)' : 'rgba(220, 53, 69, 0.9)';
    notification.style.transition = 'opacity 0.3s ease-in-out';
    notification.style.opacity = '0';
    
    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.opacity = '1';
    }, 10);

    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => {
            if (notification.parentElement) {
                notification.parentElement.removeChild(notification);
            }
        }, 300);
    }, 3000);
}

// Plot area capture and copy to clipboard
async function capturePlotAreaAndCopyToClipboard() {
    const plotArea = document.getElementById('plot-area');
    if (!plotArea || plotArea.style.display === 'none' || plotArea.children.length === 0) {
        showNotification('No plot area to capture.', 'error');
        return;
    }

    const selected = Array.from(document.querySelectorAll('.chart-container.selected'));
    const multiSelected = Array.from(document.querySelectorAll('.chart-container.multi-selected'));

    selected.forEach(el => el.classList.remove('selected'));
    multiSelected.forEach(el => el.classList.remove('multi-selected'));

    try {
        const canvas = await html2canvas(plotArea, {
            logging: false,
            useCORS: true,
            backgroundColor: '#ffffff',
        });

        canvas.toBlob(blob => {
            navigator.clipboard.write([
                new ClipboardItem({ 'image/png': blob })
            ]).then(() => {
                showNotification('Plot area copied to clipboard!');
            }).catch(err => {
                console.error('Could not copy image: ', err);
                showNotification('Failed to copy plot area.', 'error');
            });
        });

    } catch (error) {
        console.error('Error capturing plot area:', error);
        showNotification('Error capturing plot area.', 'error');
    } finally {
        selected.forEach(el => el.classList.add('selected'));
        multiSelected.forEach(el => el.classList.add('multi-selected'));
    }
}

// Keyboard shortcut for capturing plot area
document.addEventListener('keydown', async (e) => {
    if (e.altKey && e.key.toLowerCase() === 'c') {
        const activeElement = document.activeElement;
        const isTyping = ['INPUT', 'TEXTAREA'].includes(activeElement.tagName) || activeElement.isContentEditable;
        
        const plotArea = document.getElementById('plot-area');
        const isPlotAreaVisible = plotArea && plotArea.style.display !== 'none' && plotArea.children.length > 0;

        if (!isTyping && isPlotAreaVisible) {
            e.preventDefault();
            await capturePlotAreaAndCopyToClipboard();
        }
    }
});

// 차트 정보 수집 함수
function collectChartInfo() {
    const chartsInfo = [];
    
    charts.forEach((chart, index) => {
        const chartContainer = document.getElementById(chart.id);
        if (!chartContainer) return;
        
        // 현재 스케일 정보 가져오기
        const currentScale = chart.plot.scales;
        const scaleInfo = {
            x: {
                min: currentScale.x.min,
                max: currentScale.x.max
            },
            y: {
                min: currentScale.y.min,
                max: currentScale.y.max
            }
        };
        
        // 차트 순서 (CSS order 속성)
        const chartOrder = parseInt(chartContainer.style.order) || index;
        
        // 파라미터가 있는 차트만 저장
        if (chart.parameters && chart.parameters.length > 0) {
            chartsInfo.push({
                chart_id: chart.id,
                chart_order: chartOrder,
                parameters: chart.parameters,
                scale_info: scaleInfo
            });
            
            console.log(`Collected chart info for ${chart.id}:`, {
                parameters: chart.parameters,
                scale_info: scaleInfo,
                order: chartOrder
            });
        }
    });
    
    console.log(`Total charts info collected: ${chartsInfo.length}`);
    return chartsInfo;
}

// 차트 레이아웃 복원 함수
async function restoreChartLayout(chartLayout) {
    if (!chartLayout || chartLayout.length === 0) {
        console.log('No chart layout to restore');
        return;
    }
    
    console.log('Restoring chart layout:', chartLayout);
    
    // 기존 차트들 제거
    charts.forEach(chart => {
        if (chart.plot) {
            chart.plot.destroy();
        }
    });
    charts = [];
    
    // plot area 초기화
    plotArea.innerHTML = '';
    
    // 저장된 차트 정보에 따라 차트 생성
    for (const chartInfo of chartLayout) {
        const chartId = createChart();
        const chart = charts.find(c => c.id === chartId);
        
        if (chart) {
            // 차트 순서 설정
            const chartContainer = document.getElementById(chartId);
            if (chartContainer) {
                chartContainer.style.order = chartInfo.chart_order;
            }
            
            // 파라미터 적용
            if (chartInfo.parameters && chartInfo.parameters.length > 0) {
                for (const parameter of chartInfo.parameters) {
                    await updateChart(chartId, parameter);
                }
            }

            // 스케일 정보 즉시 적용
            if (chartInfo.scale_info) {
                try {
                    const scaleInfo = chartInfo.scale_info;
                    if (scaleInfo.x && scaleInfo.x.min !== undefined && scaleInfo.x.max !== undefined) {
                        chart.plot.setScale('x', {
                            min: scaleInfo.x.min,
                            max: scaleInfo.x.max
                        });
                    }
                    if (scaleInfo.y && scaleInfo.y.min !== undefined && scaleInfo.y.max !== undefined) {
                        chart.plot.setScale('y', {
                            min: scaleInfo.y.min,
                            max: scaleInfo.y.max
                        });
                    }
                    console.log(`Applied scale info to chart ${chartId}:`, scaleInfo);
                } catch (error) {
                    console.warn('Error applying scale info to chart:', error);
                }
            }
        }
    }
    
    // 모든 차트가 생성되고 데이터가 로드된 후 그리드 레이아웃 업데이트
    // DOM 렌더링을 위한 약간의 지연
    setTimeout(() => {
        updateGridLayout();
        console.log('Chart layout restored successfully');
    }, 100);
}

// Configuration Editor 관련 코드
let configData = []; // 현재 편집 중인 config 데이터

// Configuration 버튼 이벤트 핸들러
document.addEventListener('DOMContentLoaded', function() {
    // Configuration 버튼 클릭 이벤트
    const configBtn = document.getElementById('config-btn');
    if (configBtn) {
        configBtn.addEventListener('click', function(e) {
            e.preventDefault();
            showConfigEditor();
        });
    }

    // Config Editor 모달 관련 이벤트
    setupConfigEditorEvents();
});

// Configuration Editor 모달 표시
function showConfigEditor() {
    const popup = document.getElementById('config-editor-popup');
    if (popup) {
        popup.style.display = 'block';
        // 스프레드시트 기능 초기화
        setTimeout(() => {
            initializeSpreadsheet();
            // Line 색상 헤더 이벤트 설정
            setupLineColorHeaderEvents();
        }, 100);
    }
}

// Configuration Editor 이벤트 설정
function setupConfigEditorEvents() {
    // 모달 닫기
    const closeBtn = document.getElementById('config-editor-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', hideConfigEditor);
    }

    // 기존 config 파일 불러오기 - 바로 파일 탐색기 열기
    const loadExistingBtn = document.getElementById('load-existing-config');
    if (loadExistingBtn) {
        loadExistingBtn.addEventListener('click', () => {
            document.getElementById('config-file-input').click();
        });
    }

    // 새 config 생성
    const createNewBtn = document.getElementById('create-new-config');
    if (createNewBtn) {
        createNewBtn.addEventListener('click', createNewConfigFromDatabase);
    }

    // 파일 업로드 처리
    const fileInput = document.getElementById('config-file-input');
    if (fileInput) {
        fileInput.addEventListener('change', handleConfigFileUpload);
    }

    // 테이블 액션 버튼들
    const addRowBtn = document.getElementById('add-config-row');
    if (addRowBtn) {
        addRowBtn.addEventListener('click', addConfigRow);
    }

    const removeRowBtn = document.getElementById('remove-config-row');
    if (removeRowBtn) {
        removeRowBtn.addEventListener('click', removeSelectedConfigRows);
    }

    // Select All 체크박스
    const selectAllCheckbox = document.getElementById('select-all-config');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', toggleSelectAllConfigRows);
    }

    // 액션 버튼들
    const saveConfigBtn = document.getElementById('save-config-file');
    if (saveConfigBtn) {
        saveConfigBtn.addEventListener('click', saveConfigFile);
    }

    const applyConfigBtn = document.getElementById('apply-config');
    if (applyConfigBtn) {
        applyConfigBtn.addEventListener('click', applyConfig);
    }
}

// Configuration Editor 초기화
function resetConfigEditor() {
    // 모든 섹션 숨기기
    document.getElementById('config-table-section').style.display = 'none';
    document.getElementById('config-actions').style.display = 'none';
    
    // 로드 옵션 섹션만 표시
    document.getElementById('config-load-options').style.display = 'block';
    
    // 파일 입력 초기화
    const fileInput = document.getElementById('config-file-input');
    if (fileInput) {
        fileInput.value = '';
    }
    
    // 테이블 초기화
    configData = [];
    window.missingParameters = [];
    updateConfigTable();
}

// Configuration Editor 숨기기
function hideConfigEditor() {
    const configEditorPopup = document.getElementById('config-editor-popup');
    if (configEditorPopup) {
        configEditorPopup.style.display = 'none';
    }
}



// 데이터베이스에서 기존 config 로드 또는 새로 생성
async function createNewConfigFromDatabase() {
    try {
        // 먼저 기존 설정이 있는지 확인
        const loadResponse = await fetch('/api/config/load');
        const loadResult = await loadResponse.json();
        
        if (loadResponse.ok && loadResult.config_data && loadResult.config_data.length > 0) {
            // 기존 설정이 있으면 로드
            configData = loadResult.config_data;
            window.configData = configData;
            showConfigTable();
            showNotification('Loaded existing configuration.');
        } else {
            // 기존 설정이 없으면 파라미터 목록으로 새로 생성
            const response = await fetch('/api/parameters');
            const parameters = await response.json();
            
            if (response.ok && parameters.length > 0) {
                // 기본 config 데이터 생성
                configData = parameters.map(param => ({
                    parameter_name: param,
                    description: '',
                    type: 'Raw',
                    formula: '',
                    custom_py: '',
                    lo: '',
                    hi: '',
                    line1: '',
                    line2: '',
                    line3: '',
                    line4: '',
                    line5: '',
                    line6: ''
                }));
                window.configData = configData;
                showConfigTable();
                showNotification('Created new configuration from parameters.');
            } else {
                showNotification('No parameters found in database.', 'error');
            }
        }
    } catch (error) {
        console.error('Error loading/creating config:', error);
        showNotification('Error loading/creating config.', 'error');
    }
}

// Config 파일 업로드 처리
async function handleConfigFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/config/upload', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            configData = result.config_data;
            window.configData = configData;
            window.missingParameters = result.missing_parameters || [];
            // Config에만 있고 DB에는 없는 Raw 파라미터 목록
            window.notInDbParameters = [];
            if (result.config_parameters && result.db_parameters) {
                window.notInDbParameters = result.config_data
                    .filter(row => row.type === 'Raw' && !result.db_parameters.includes(row.parameter_name))
                    .map(row => row.parameter_name);
            }
            showConfigTable();
            
            // 추가된 파라미터 정보 표시
            if (result.missing_parameters && result.missing_parameters.length > 0) {
                const missingCount = result.missing_parameters.length;
                const totalCount = result.config_data.length;
                const configCount = result.config_parameters.length;
                
                showNotification(
                    `Configuration file "${file.name}" loaded successfully! ` +
                    `Found ${configCount} parameters in config, ` +
                    `added ${missingCount} missing parameters from database. ` +
                    `Total: ${totalCount} parameters.`,
                    'info'
                );
            } else {
                showNotification(`Configuration file "${file.name}" loaded successfully! All database parameters are included.`);
            }
        } else {
            throw new Error(result.error);
        }
    } catch (error) {
        console.error('Error uploading config file:', error);
        showNotification(`Error uploading config file: ${error.message}`, 'error');
    }
}

// Config 테이블 표시
function showConfigTable() {
    document.getElementById('config-load-options').style.display = 'none';
    document.getElementById('config-table-section').style.display = 'block';
    document.getElementById('config-actions').style.display = 'block';
    
    // configData에서 라인 색상 정보를 window.lineColors에 복원
    if (configData && configData.length > 0) {
        if (!window.lineColors) {
            window.lineColors = ['#ddd', '#ddd', '#ddd', '#ddd', '#ddd', '#ddd'];
        }
        
        for (let i = 1; i <= 6; i++) {
            const colorField = `line${i}_color`;
            for (const row of configData) {
                if (row[`line${i}`] && row[`line${i}`] !== '' && row[colorField]) {
                    window.lineColors[i-1] = row[colorField];
                    break;
                }
            }
        }
    }
    
    updateConfigTable();
    
    // Line 색상 헤더 이벤트 설정
    setTimeout(() => {
        setupLineColorHeaderEvents();
    }, 100);
}

// Config 테이블 업데이트
function updateConfigTable() {
    const tbody = document.getElementById('config-table-body');
    if (!tbody) {
        console.log('Config table body not found, skipping update');
        return;
    }
    
    tbody.innerHTML = '';
    
    // 안전한 currentSelection 계산
    let currentSelection = null;
    if (selectedCell && selectedCell.parentElement && selectedCell.parentElement.parentElement) {
        currentSelection = {
            rowIndex: Array.from(selectedCell.parentElement.parentElement.children).indexOf(selectedCell.parentElement),
            colIndex: Array.from(selectedCell.parentElement.children).indexOf(selectedCell)
        };
    }
    
    configData.forEach((row, index) => {
        const tr = document.createElement('tr');
        tr.setAttribute('data-index', index);

        // New 표기
        const isMissingParameter = window.missingParameters && window.missingParameters.includes(row.parameter_name);
        if (isMissingParameter) {
            tr.classList.add('config-table-row', 'missing-parameter');
        } else {
            tr.classList.add('config-table-row');
        }

        // Not in DB 표기
        const isNotInDb = window.notInDbParameters && window.notInDbParameters.includes(row.parameter_name);

        tr.innerHTML = `
            <td class="editable-cell" data-field="parameter_name" data-index="${index}" data-type="text">
                ${row.parameter_name || ''}
                ${isNotInDb ? '<span class="not-in-db-label">Not in DB</span>' : ''}
                ${isMissingParameter ? '<span class="new-label">New</span>' : ''}
            </td>
            <td class="editable-cell" data-field="description" data-index="${index}" data-type="text">${row.description || ''}</td>
            <td class="editable-cell" data-field="type" data-index="${index}" data-type="select" data-options="Raw,Derived">${row.type || 'Raw'}</td>
            <td class="editable-cell" data-field="formula" data-index="${index}" data-type="textarea">${row.formula || ''}</td>
            <td class="editable-cell" data-field="custom_py" data-index="${index}" data-type="file">${row.custom_py || '첨부(.py)'}</td>
            <td class="editable-cell" data-field="lo" data-index="${index}" data-type="number">${row.lo || ''}</td>
            <td class="editable-cell" data-field="hi" data-index="${index}" data-type="number">${row.hi || ''}</td>
            <td class="editable-cell" data-field="line1" data-index="${index}" data-type="line">
                ${row.line1 ? `<span class='color-indicator' style='background-color: ${row.line1}'></span>${row.line1}` : ''}
            </td>
            <td class="editable-cell" data-field="line2" data-index="${index}" data-type="line">
                ${row.line2 ? `<span class='color-indicator' style='background-color: ${row.line2}'></span>${row.line2}` : ''}
            </td>
            <td class="editable-cell" data-field="line3" data-index="${index}" data-type="line">
                ${row.line3 ? `<span class='color-indicator' style='background-color: ${row.line3}'></span>${row.line3}` : ''}
            </td>
            <td class="editable-cell" data-field="line4" data-index="${index}" data-type="line">
                ${row.line4 ? `<span class='color-indicator' style='background-color: ${row.line4}'></span>${row.line4}` : ''}
            </td>
            <td class="editable-cell" data-field="line5" data-index="${index}" data-type="line">
                ${row.line5 ? `<span class='color-indicator' style='background-color: ${row.line5}'></span>${row.line5}` : ''}
            </td>
            <td class="editable-cell" data-field="line6" data-index="${index}" data-type="line">
                ${row.line6 ? `<span class='color-indicator' style='background-color: ${row.line6}'></span>${row.line6}` : ''}
            </td>
        `;
        tbody.appendChild(tr);
    });

    // 행 클릭 시 선택 (탭처럼)
    Array.from(tbody.children).forEach(tr => {
        tr.addEventListener('click', function(e) {
            // 이미 선택된 행이면 해제
            if (tr.classList.contains('row-selected')) {
                tr.classList.remove('row-selected');
                selectedCell = null;
                updateSpreadsheetStatus('Ready');
                return;
            }
            // 모든 행 선택 해제
            Array.from(tbody.children).forEach(r => r.classList.remove('row-selected'));
            tr.classList.add('row-selected');
            // 첫 번째 셀을 선택 셀로 지정
            const firstCell = tr.querySelector('.editable-cell');
            if (firstCell) {
                selectCell(firstCell);
            }
        });
    });

    // 안전한 셀 선택 복원
    if (currentSelection && currentSelection.rowIndex < tbody.children.length) {
        const newRow = tbody.children[currentSelection.rowIndex];
        if (newRow && newRow.children[currentSelection.colIndex]) {
            selectCell(newRow.children[currentSelection.colIndex]);
        }
    }
    
    setupConfigTableEventListeners();
    initializeSpreadsheet();
    
    // 헤더 컬러바도 갱신
    updateLineColorBars();
}

// Line 색상 바 업데이트 함수
function updateLineColorBars() {
    for (let i = 1; i <= 6; i++) {
        const bar = document.getElementById(`line${i}-color-bar`);
        if (bar) {
            // 해당 라인의 색상이 설정되어 있으면 사용, 없으면 기본 색상
            const lineField = `line${i}`;
            const colorField = `line${i}_color`;
            
            // 먼저 configData에서 색상 정보를 찾음
            let color = null;
            for (const row of configData) {
                if (row[lineField] && row[lineField] !== '' && row[colorField]) {
                    color = row[colorField];
                    break;
                }
            }
            
            // configData에서 찾지 못하면 window.lineColors에서 찾음
            if (!color && window.lineColors && window.lineColors[i-1]) {
                color = window.lineColors[i-1];
            }
            
            // 기본 색상 설정
            if (color) {
                bar.style.background = color;
                console.log(`Set line${i} color bar to: ${color}`);
            } else {
                bar.style.background = '#ddd'; // 기본 색상
                console.log(`Set line${i} color bar to default: #ddd`);
            }
        }
    }
}

// Config 테이블 이벤트 리스너 설정
function setupConfigTableEventListeners() {
    // 입력 필드 변경 이벤트
    document.querySelectorAll('.config-input').forEach(input => {
        input.addEventListener('input', function() {
            const index = parseInt(this.getAttribute('data-index'));
            const field = this.getAttribute('data-field');
            const value = this.value.trim();
            
            if (configData[index]) {
                // Line 필드의 경우 0 값을 빈 문자열로 처리
                if (field.startsWith('line') && (value === '0' || value === '')) {
                    configData[index][field] = '';
                } else {
                    configData[index][field] = value;
                }
            }
        });
    });

    // 행 선택 체크박스 이벤트
    document.querySelectorAll('.config-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const index = parseInt(this.getAttribute('data-index'));
            const row = this.closest('tr');
            
            if (this.checked) {
                row.classList.add('selected');
            } else {
                row.classList.remove('selected');
            }
        });
    });
    
    // CSV 내보내기 버튼 이벤트
    const exportCsvBtn = document.getElementById('export-config-csv');
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener('click', exportConfigToCSV);
    }
    
    // CSV 가져오기 버튼 이벤트
    const importCsvBtn = document.getElementById('import-config-csv');
    if (importCsvBtn) {
        importCsvBtn.addEventListener('click', importConfigFromCSV);
    }
    
    // Line 헤더 클릭 이벤트 설정
    setupLineColorHeaderEvents();
}

// Line 색상 팔레트 관련 함수들
function setupLineColorHeaderEvents() {
    console.log('Setting up line color header events...');
    
    // 테이블 헤더에 이벤트 위임 사용
    const thead = document.querySelector('#config-table thead');
    if (thead) {
        console.log('Found thead:', thead);
        
        // 기존 이벤트 리스너 제거
        thead.removeEventListener('click', handleTheadClick);
        
        // 새로운 이벤트 리스너 추가
        thead.addEventListener('click', handleTheadClick);
        console.log('Added click event listener to thead');
    }
    
    console.log('Line color header events setup complete');
}

function handleTheadClick(e) {
    const target = e.target.closest('[data-line-header]');
    if (target) {
        e.preventDefault();
        e.stopPropagation();
        
        const lineNumber = target.getAttribute('data-line-header');
        console.log('Line header clicked:', lineNumber);
        showLineColorPalette(target, lineNumber);
    }
}

function showLineColorPalette(headerElement, lineNumber) {
    console.log('Showing color palette for line:', lineNumber);
    
    // 팔레트가 없으면 동적으로 생성
    let palette = document.getElementById('line-color-palette');
    if (!palette) {
        console.log('Creating palette dynamically');
        palette = createColorPalette();
        document.body.appendChild(palette);
    }
    
    const colorSwatches = palette.querySelector('.color-swatches');
    if (!colorSwatches) {
        console.error('Color swatches container not found');
        return;
    }
    
    // 기존 색상 스왓치 제거
    colorSwatches.innerHTML = '';
    
    // 색상 옵션들
    const colors = [
        '#FF0000', '#00FF00', '#0000FF', '#FF6600', '#9900FF', '#00CC00',
        '#FF00FF', '#00FFFF', '#FFD700', '#FF4500', '#8A2BE2', '#32CD32',
        '#FF1493', '#00CED1', '#FF8C00', '#9932CC', '#FF6B6B', '#4ECDC4',
        '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F'
    ];
    
    // 색상 스왓치 생성
    colors.forEach(color => {
        const swatch = document.createElement('div');
        swatch.className = 'color-swatch';
        swatch.style.backgroundColor = color;
        swatch.setAttribute('data-color', color);
        swatch.setAttribute('data-line', lineNumber);
        
        swatch.addEventListener('click', function() {
            console.log('Color selected:', color, 'for line:', lineNumber);
            selectLineColor(color, lineNumber);
            hideLineColorPalette();
        });
        
        colorSwatches.appendChild(swatch);
    });
    
    // 팔레트 위치 설정
    const headerRect = headerElement.getBoundingClientRect();
    palette.style.left = headerRect.left + 'px';
    palette.style.top = (headerRect.bottom + 5) + 'px';
    
    console.log('Palette position:', palette.style.left, palette.style.top);
    
    // 팔레트 표시
    palette.classList.add('show');
    console.log('Palette shown');
    
    // 팔레트 외부 클릭 시 닫기
    const closePalette = function(e) {
        if (!palette.contains(e.target) && !headerElement.contains(e.target)) {
            hideLineColorPalette();
            document.removeEventListener('click', closePalette);
        }
    };
    document.addEventListener('click', closePalette);
    
    // 닫기 버튼 이벤트
    const closeBtn = palette.querySelector('.palette-close-btn');
    if (closeBtn) {
        closeBtn.addEventListener('click', function() {
            hideLineColorPalette();
        });
    }
}

function createColorPalette() {
    const palette = document.createElement('div');
    palette.id = 'line-color-palette';
    palette.className = 'line-color-palette';
    
    palette.innerHTML = `
        <div class="palette-header">
            <span>Select Line Color</span>
            <button class="palette-close-btn">&times;</button>
        </div>
        <div class="palette-content">
            <div class="color-swatches">
                <!-- Color swatches will be populated here -->
            </div>
        </div>
    `;
    
    return palette;
}

function hideLineColorPalette() {
    console.log('Hiding color palette');
    const palette = document.getElementById('line-color-palette');
    if (palette) {
        palette.classList.remove('show');
    }
}

function selectLineColor(color, lineNumber) {
    console.log(`Setting line ${lineNumber} color to ${color}`);
    
    // 전역 색상 변수에 저장 (Fixed Scale에서 사용)
    if (!window.lineColors) {
        window.lineColors = ['#ddd', '#ddd', '#ddd', '#ddd', '#ddd', '#ddd'];
    }
    window.lineColors[lineNumber - 1] = color;
    
    // configData의 모든 행에 해당 라인 색상 정보 저장
    const lineField = `line${lineNumber}`;
    configData.forEach(row => {
        if (row[lineField] && row[lineField] !== '') {
            // 기존 값이 있으면 색상 정보를 추가
            row[`line${lineNumber}_color`] = color;
        }
    });
    
    // 색상 바 업데이트
    updateLineColorBar(lineNumber, color);
    
    // Fixed Scale이 활성화되어 있다면 모든 차트에 색상 변경 적용
    if (isFixedScale) {
        applyFixedScaleToAllCharts();
    }
    
    console.log(`Line ${lineNumber} color set to ${color} and saved to configData`);
}

function updateLineColorBar(lineNumber, color) {
    console.log(`Updating color bar for line ${lineNumber} to ${color}`);
    const colorBar = document.getElementById(`line${lineNumber}-color-bar`);
    if (colorBar) {
        colorBar.style.backgroundColor = color;
        console.log(`Color bar updated successfully`);
    } else {
        console.error(`Color bar element not found for line ${lineNumber}`);
    }
}

// Config 행 추가
function addConfigRow() {
    const newRow = {
        parameter_name: '',
        description: '',
        type: 'Derived', // 기본값을 Derived로
        formula: '',
        custom_py: '',
        lo: '',
        hi: '',
        line1: '',
        line2: '',
        line3: '',
        line4: '',
        line5: '',
        line6: ''
    };
    
    configData.push(newRow);
    updateConfigTable();
}

// 선택된 Config 행 삭제
function removeSelectedConfigRows() {
    const selectedCheckboxes = document.querySelectorAll('.config-checkbox:checked');
    const selectedIndices = Array.from(selectedCheckboxes).map(cb => parseInt(cb.getAttribute('data-index')));
    
    if (selectedIndices.length === 0) {
        showNotification('Please select rows to remove.', 'error');
        return;
    }
    
    // 인덱스를 내림차순으로 정렬하여 뒤에서부터 삭제
    selectedIndices.sort((a, b) => b - a);
    
    selectedIndices.forEach(index => {
        configData.splice(index, 1);
    });
    
    updateConfigTable();
    showNotification(`${selectedIndices.length} row(s) removed.`);
}

// 모든 Config 행 선택/해제
function toggleSelectAllConfigRows() {
    const selectAllCheckbox = document.getElementById('select-all-config');
    const rowCheckboxes = document.querySelectorAll('.config-checkbox');
    
    rowCheckboxes.forEach(checkbox => {
        checkbox.checked = selectAllCheckbox.checked;
        const row = checkbox.closest('tr');
        
        if (selectAllCheckbox.checked) {
            row.classList.add('selected');
        } else {
            row.classList.remove('selected');
        }
    });
}

// Config 파일 저장
async function saveConfigFile() {
    if (configData.length === 0) {
        showNotification('No configuration data to save.', 'error');
        return;
    }

    // 모달 표시
    const modal = document.getElementById('save-config-modal');
    const filenameInput = document.getElementById('config-filename');
    const closeBtn = document.getElementById('save-config-modal-close');
    const cancelBtn = document.getElementById('save-config-cancel');
    const form = document.getElementById('save-config-form');

    // 기본값 설정
    filenameInput.value = 'config';
    filenameInput.focus();
    filenameInput.select();

    modal.style.display = 'block';

    // 모달 닫기 함수
    let closeModal = () => {
        modal.style.display = 'none';
        filenameInput.value = '';
    };

    // 이벤트 리스너 설정
    const handleClose = () => closeModal();
    const handleCancel = () => closeModal();
    
    closeBtn.addEventListener('click', handleClose);
    cancelBtn.addEventListener('click', handleCancel);

    // 모달 외부 클릭 시 닫기
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });

    // 폼 제출 처리
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const filename = filenameInput.value.trim();
        
        if (filename === '') {
            showNotification('Please enter a valid file name.', 'error');
            return;
        }

        try {
            const response = await fetch('/api/config/save', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    config_data: configData,
                    filename: filename
                })
            });

            const result = await response.json();

            if (response.ok) {
                showNotification(`Configuration saved successfully as ${result.filename}!`);
                closeModal();
            } else {
                throw new Error(result.error);
            }
        } catch (error) {
            console.error('Error saving config:', error);
            showNotification(`Error saving config: ${error.message}`, 'error');
        }
    });

    // 이벤트 리스너 정리 함수
    const cleanup = () => {
        closeBtn.removeEventListener('click', handleClose);
        cancelBtn.removeEventListener('click', handleCancel);
    };

    // 모달이 닫힐 때 정리
    const originalCloseModal = closeModal;
    closeModal = () => {
        originalCloseModal();
        cleanup();
    };
}

// CSV 내보내기 함수
async function exportConfigToCSV() {
    try {
        // 현재 Config 데이터 가져오기
        if (!configData || configData.length === 0) {
            showNotification('No configuration data to export.', 'error');
            return;
        }
        
        console.log('Exporting configuration to CSV...');
        
        const response = await fetch('/api/config/export_csv', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                config_data: configData
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showNotification('Configuration exported to CSV successfully!');
            console.log('CSV export successful:', result);
            
            // 파일 다운로드 링크 생성
            const downloadLink = document.createElement('a');
            downloadLink.href = `/uploads/${result.filename}`;
            downloadLink.download = result.filename;
            downloadLink.style.display = 'none';
            document.body.appendChild(downloadLink);
            downloadLink.click();
            document.body.removeChild(downloadLink);
            
        } else {
            throw new Error(result.error);
        }
    } catch (error) {
        console.error('Error exporting config to CSV:', error);
        showNotification(`Error exporting config: ${error.message}`, 'error');
    }
}

// CSV 가져오기 함수
async function importConfigFromCSV() {
    try {
        // 파일 입력 요소 생성
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.csv';
        fileInput.style.display = 'none';
        
        fileInput.addEventListener('change', async function(e) {
            const file = e.target.files[0];
            if (!file) {
                return;
            }
            
            if (!file.name.endsWith('.csv')) {
                showNotification('Please select a CSV file.', 'error');
                return;
            }
            
            console.log('Importing configuration from CSV...');
            
            const formData = new FormData();
            formData.append('file', file);
            
            const response = await fetch('/api/config/import_csv', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (response.ok) {
                console.log('CSV import successful:', result);
                
                // Config 데이터 업데이트
                configData = result.config_data;
                window.configData = configData;
                
                // 누락된 파라미터와 Not in DB 파라미터 정보 저장
                window.missingParameters = result.missing_parameters || [];
                window.notInDbParameters = result.not_in_db_parameters || [];
                
                // Config 테이블 업데이트
                updateConfigTable();
                
                // Config 섹션 표시
                document.getElementById('config-table-section').style.display = 'block';
                document.getElementById('config-actions').style.display = 'block';
                
                // 추가된 파라미터 정보 표시
                if (result.missing_parameters && result.missing_parameters.length > 0) {
                    const missingCount = result.missing_parameters.length;
                    const totalCount = result.config_data.length;
                    const configCount = result.config_parameters.length;
                    
                    showNotification(
                        `Configuration imported from CSV "${file.name}" successfully! ` +
                        `Found ${configCount} parameters in CSV, ` +
                        `added ${missingCount} missing parameters from database. ` +
                        `Total: ${totalCount} parameters.`,
                        'info'
                    );
                } else {
                    showNotification(`Configuration imported from CSV "${file.name}" successfully! All database parameters are included.`);
                }
                
            } else {
                throw new Error(result.error);
            }
        });
        
        // 파일 선택 다이얼로그 열기
        document.body.appendChild(fileInput);
        fileInput.click();
        document.body.removeChild(fileInput);
        
    } catch (error) {
        console.error('Error importing config from CSV:', error);
        showNotification(`Error importing config: ${error.message}`, 'error');
    }
}

// Config 적용
async function applyConfig() {
    if (configData.length === 0) {
        showNotification('No configuration data to apply.', 'error');
        return;
    }

    try {
        // Custom(.py) 파일이 있는지 확인하고 NewDerived 기능으로 처리
        const customPyConfigs = configData.filter(config => 
            config.custom_py_content && config.type === 'Derived'
        );
        
        if (customPyConfigs.length > 0) {
            console.log(`Found ${customPyConfigs.length} custom .py files to process`);
            
            // 각 Custom(.py) 파일을 NewDerived 기능으로 처리
            for (const config of customPyConfigs) {
                try {
                    console.log(`Processing custom .py file for parameter: ${config.parameter_name}`);
                    
                    // 사용 가능한 파라미터 목록 가져오기
                    const paramItems = document.querySelectorAll('.parameter-item');
                    const availableParams = Array.from(paramItems).map(x => x.textContent.trim());
                    
                    // Custom(.py) 파일에서 사용된 파라미터 추출
                    const usedParams = extractParameterNamesFromCode(config.custom_py_content, availableParams);
                    
                    if (usedParams.length === 0) {
                        console.warn(`No valid parameters found in custom .py file for: ${config.parameter_name}`);
                        continue;
                    }
                    
                    console.log(`Extracted parameters from custom .py: ${usedParams}`);
                    
                    const data = await runBackgroundJob('derived', {
                        name: config.parameter_name,
                        code: config.custom_py_content,
                        parameters: usedParams,
                        alignment: alignmentPolicy
                    });
                    if (data) {
                        console.log(`Successfully created derived parameter from custom .py: ${config.parameter_name}`);
                    }
                    
                } catch (error) {
                    console.error(`Error processing custom .py file for ${config.parameter_name}:`, error);
                }
            }
        }
        
        // 기존 Config 적용
        const response = await fetch('/api/config/apply', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                config_data: configData
            })
        });

        const result = await response.json();
        
        console.log('Configuration apply response:', result);

        if (response.ok) {
            showNotification('Configuration applied successfully!');
            window.configData = configData;
            
            console.log('Checking refresh_parameters flag:', result.refresh_parameters);
            
            // refresh_parameters 플래그가 있으면 파라미터 목록 새로고침
            if (result.refresh_parameters) {
                console.log('Refreshing parameters list...');
                await loadParameters();
                console.log('Parameters list refreshed');
            } else {
                console.log('No refresh_parameters flag, skipping parameter list refresh');
            }
            
            // 모든 차트 타이틀 업데이트 (Config 적용 후)
            updateAllChartTitles();
            
            hideConfigEditor();
        } else {
            throw new Error(result.error);
        }
    } catch (error) {
        console.error('Error applying config:', error);
        showNotification(`Error applying config: ${error.message}`, 'error');
    }
}

// 토글 버튼 이벤트 리스너 설정
function setupToggleEventListeners() {
    // Show Description 토글
    const showDescriptionToggle = document.getElementById('show-description-toggle');
    if (showDescriptionToggle) {
        showDescriptionToggle.addEventListener('change', function() {
            isShowDescription = this.checked;
            console.log('Show Description toggle:', isShowDescription);
            
            // 파라미터 리스트 업데이트
            loadParameters();
            
            // 모든 차트 타이틀 업데이트
            updateAllChartTitles();
        });
    }
    
    // Fixed Scale 토글
    const fixedScaleToggle = document.getElementById('fixed-scale-toggle');
    if (fixedScaleToggle) {
        fixedScaleToggle.addEventListener('change', function() {
            isFixedScale = this.checked;
            console.log('Fixed Scale toggle:', isFixedScale);
            applyFixedScaleToAllCharts();
        });
    }

    // Transparency 슬라이더 이벤트
    const lineAlphaSlider = document.getElementById('line-alpha-slider');
    const lineAlphaValue = document.getElementById('line-alpha-value');
    if (lineAlphaSlider) {
        const initial = parseFloat(lineAlphaSlider.value);
        lineAlphaPercent = isNaN(initial) ? 0 : Math.min(100, Math.max(0, initial));
        if (lineAlphaValue) lineAlphaValue.textContent = `${Math.round(lineAlphaPercent)}%`;
        applyLineTransparencyToAllCharts();

        const onSlide = function() {
            let val = parseFloat(lineAlphaSlider.value);
            if (isNaN(val)) val = 0;
            val = Math.min(100, Math.max(0, val));
            lineAlphaPercent = val;
            if (lineAlphaValue) lineAlphaValue.textContent = `${Math.round(val)}%`;
            applyLineTransparencyToAllCharts();
        };
        lineAlphaSlider.addEventListener('input', onSlide);
        lineAlphaSlider.addEventListener('change', onSlide);
    }
}

// Fixed Scale 적용 함수
function applyFixedScaleToAllCharts() {
    charts.forEach(chart => {
        if (chart.parameters.length >= 1) {
            const param = chart.parameters[0];
            const config = (window.configData || []).find(c => c.parameter_name === param);
            
            if (isFixedScale && config) {
                // Fixed Scale 적용
                if (isFinite(Number(config.lo)) && isFinite(Number(config.hi))) {
                    chart.plot.setScale('y', { min: Number(config.lo), max: Number(config.hi) });
                }
                
                // Line1~6 시리즈 추가
                addLimitLineSeries(chart, config);
                
                // Line1~6이 적용된 파라미터 확인
                const hasLinesApplied = [];
                for (let i = 1; i <= 6; i++) {
                    const lineValue = config[`line${i}`];
                    if (lineValue !== '' && lineValue !== null && lineValue !== undefined && lineValue !== 0) {
                        const numericValue = Number(lineValue);
                        if (isFinite(numericValue)) {
                            hasLinesApplied.push(i);
                        }
                    }
                }
                
                // 시리즈 가시성 설정 - Line1~6이 있으면 모든 파라미터 표시, 없으면 원래 상태 유지
                if (chart.plot && chart.plot.series) {
                    chart.plot.series.forEach((series, index) => {
                        if (index === 0) {
                            // Time 시리즈는 항상 표시
                            series.show = true;
                        } else if (index <= chart.parameters.length) {
                            // 파라미터 시리즈 (index 1부터)
                            const paramIndex = index - 1;
                            const paramName = chart.parameters[paramIndex];
                            
                            // Line1~6이 있으면 모든 파라미터 표시, 없으면 원래 상태 유지
                            if (hasLinesApplied.length > 0) {
                                series.show = true;
                            } else {
                                // 원래 로직 적용 (유효한 데이터가 있는지 확인)
                                const hasValidData = chart.data && chart.data.values && 
                                                   chart.data.values[index - 1] && 
                                                   chart.data.values[index - 1].some(value => !isNaN(value));
                                series.show = hasValidData;
                            }
                        } else {
                            // Line1~6 시리즈는 항상 표시 (dash 속성으로 식별)
                            const isLimitLine = series.dash && series.dash.length === 2 && 
                                              series.dash[0] === 5 && series.dash[1] === 5 && 
                                              series.width === 1;
                            series.show = isLimitLine;
                        }
                    });
                }
                
                // 차트 제목 업데이트
                updateChartTitle(chart);
            } else {
                // 오토스케일로 복원
                const yValues = (chart.data && chart.data.values && chart.data.values[0]) ? chart.data.values[0].filter(v => isFinite(v)) : [];
                if (yValues.length > 0) {
                    const yMin = Math.min(...yValues);
                    const yMax = Math.max(...yValues);
                    if (isFinite(yMin) && isFinite(yMax) && yMin !== yMax) {
                        chart.plot.setScale('y', { min: yMin, max: yMax });
                    }
                } else {
                    chart.plot.setScale('y', { min: 0, max: 1 });
                }
                
                // 원래 시리즈 가시성 상태로 복원 (updateChartData에서 설정한 로직과 동일)
                if (chart.plot && chart.plot.series) {
                    chart.plot.series.forEach((series, index) => {
                        if (index === 0) {
                            // Time 시리즈는 항상 표시
                            series.show = true;
                        } else if (index <= chart.parameters.length) {
                            // 파라미터 시리즈 (index 1부터) - 원래 로직 적용
                            const hasValidData = chart.data && chart.data.values && 
                                               chart.data.values[index - 1] && 
                                               chart.data.values[index - 1].some(value => !isNaN(value));
                            series.show = hasValidData;
                        } else {
                            // Line1~6 시리즈는 제거되므로 표시하지 않음
                            series.show = false;
                        }
                    });
                }
                
                // Line1~6 시리즈 제거
                removeLimitLineSeries(chart);
                
                // 차트 제목 복원
                updateChartTitle(chart);
            }
        }
    });
}

// Limit Line 시리즈 추가 함수
function addLimitLineSeries(chart, config) {
    if (!chart.data || !chart.data.time || chart.data.time.length === 0) return;
    
    const timeData = chart.data.time;
    
    // 기존 Limit Line 시리즈 제거
    removeLimitLineSeries(chart);
    
    // 기존 데이터에 Limit Line 데이터 추가
    const currentData = chart.plot.data;
    const newData = [...currentData];
    
    // Line1~6 처리
    for (let i = 1; i <= 6; i++) {
        const lineValue = config[`line${i}`];
        // 저장된 색상 정보 사용 (config에서 먼저 확인, 없으면 window.lineColors 사용)
        let lineColor = config[`line${i}_color`] || window.lineColors?.[i-1] || '#FF0000';
        
        // 값이 입력되지 않은 경우 (빈 문자열, null, undefined, 0이 아닌 경우) 건너뛰기
        if (lineValue === '' || lineValue === null || lineValue === undefined || lineValue === 0) {
            continue;
        }
        
        const numericValue = Number(lineValue);
        if (isFinite(numericValue)) {
            const lineData = new Float64Array(timeData.length);
            lineData.fill(numericValue);
            
            newData.push(lineData);
            chart.plot.addSeries({
                // label: `Line${i}`, // legend에 표시되지 않도록 label 제거
                stroke: lineColor,
                scale: 'y',
                dash: [5, 5], // 점선 패턴
                width: 1
            });
        }
    }
    
    // 차트 데이터 업데이트
    if (newData.length > currentData.length) {
        chart.plot.setData(newData);
    }
}

// 차트 타이틀 업데이트 함수
function updateChartTitle(chart) {
    const chartContainer = document.getElementById(chart.id);
    if (!chartContainer) return;
    const titleElement = chartContainer.querySelector('.chart-title');
    const countElement = chartContainer.querySelector('.chart-channel-count');
    if (!titleElement) return;

    if (countElement) {
        countElement.textContent = chart.parameters.length ? `${chart.parameters.length} CH` : 'EMPTY';
    }

    if (chart.parameters.length === 0) {
        titleElement.textContent = 'Select chart, then choose a channel';
        return;
    }
    
    if (isShowDescription) {
        // Description 표시 모드
        const seriesColors = ['#2196F3', '#FF5722', '#4CAF50']; // 라인 색상 배열
        const coloredTitle = chart.parameters.map((param, index) => {
            const color = seriesColors[index % seriesColors.length];
            
            // Config에서 Description 찾기
            const config = (window.configData || []).find(c => c.parameter_name === param);
            const description = config ? config.description : '';
            
            // Description이 있으면 Description 사용, 없으면 파라미터 이름 사용
            const displayText = description && description.trim() !== '' ? description : param;
            
            return `<span style="color: ${color}">${escapeHtml(displayText)}</span>`;
        }).join(' vs ');
        
        titleElement.innerHTML = coloredTitle;
    } else {
        // 파라미터 이름 표시 모드 (기본)
        const seriesColors = ['#2196F3', '#FF5722', '#4CAF50']; // 라인 색상 배열
        const coloredTitle = chart.parameters.map((param, index) => {
            const color = seriesColors[index % seriesColors.length];
            return `<span style="color: ${color}">${escapeHtml(param)}</span>`;
        }).join(' vs ');
        
        titleElement.innerHTML = coloredTitle;
    }
}

// 모든 차트 타이틀 업데이트 함수
function updateAllChartTitles() {
    charts.forEach(chart => {
        updateChartTitle(chart);
    });
}

// Limit Line 시리즈 제거 함수
function removeLimitLineSeries(chart) {
    if (!chart.plot || !chart.plot.series) return;
    
    const series = chart.plot.series;
    const limitSeriesIndices = [];
    
    // Limit Line 시리즈 인덱스 찾기 (Line1~6)
    // label이 제거되었으므로 dash 속성과 width 속성으로 식별
    for (let i = 0; i < series.length; i++) {
        if (series[i].dash && series[i].dash.length === 2 && 
            series[i].dash[0] === 5 && series[i].dash[1] === 5 && 
            series[i].width === 1) {
            limitSeriesIndices.push(i);
        }
    }
    
    // 뒤에서부터 제거 (인덱스 변화 방지)
    limitSeriesIndices.reverse().forEach(index => {
        chart.plot.delSeries(index);
    });
}

// 페이지 로드 시 토글 이벤트 리스너 설정
window.addEventListener('load', function() {
    setupToggleEventListeners();
});

// Plot 탭에서 configData가 없으면 자동으로 불러오기
async function ensureConfigDataLoaded() {
    if (!window.configData || !Array.isArray(window.configData) || window.configData.length === 0) {
        try {
            const response = await fetch('/api/config/load');
            const result = await response.json();
            if (response.ok && result.config_data) {
                window.configData = result.config_data;
            }
        } catch (e) {
            window.configData = [];
        }
    }
}

// Spreadsheet functionality
let selectedCell = null;
let clipboardData = null;
let isEditing = false;

// Spreadsheet initialization
function initializeSpreadsheet() {
    const table = document.getElementById('config-table');
    if (!table) return;
    
    // Add event listeners for spreadsheet functionality
    setupSpreadsheetEventListeners();
    setupSpreadsheetKeyboardNavigation();
    setupSpreadsheetToolbar();
}

// Setup spreadsheet event listeners
function setupSpreadsheetEventListeners() {
    const table = document.getElementById('config-table');
    if (!table) {
        console.log('Config table not found, skipping event listener setup');
        return;
    }
    
    const tbody = table.querySelector('tbody');
    if (!tbody) {
        console.log('Config table tbody not found, skipping event listener setup');
        return;
    }
    
    // Cell click for selection
    tbody.addEventListener('click', function(e) {
        const cell = e.target.closest('td');
        if (cell && cell.classList.contains('editable-cell')) {
            selectCell(cell);
        }
    });
    
    // Double click for editing
    tbody.addEventListener('dblclick', function(e) {
        const cell = e.target.closest('td');
        if (cell && cell.classList.contains('editable-cell')) {
            startCellEditing(cell);
        }
    });
    
    // Click outside to deselect
    document.addEventListener('click', function(e) {
        if (!e.target.closest('#config-table')) {
            clearSelection();
        }
    });
}

// Setup keyboard navigation
function setupSpreadsheetKeyboardNavigation() {
    document.addEventListener('keydown', function(e) {
        if (!selectedCell) return;
        
        const currentRow = selectedCell.parentElement;
        if (!currentRow) return;
        
        const currentIndex = Array.from(currentRow.children).indexOf(selectedCell);
        const tbody = document.getElementById('config-table-body');
        if (!tbody) return;
        
        const rows = Array.from(tbody.children);
        const currentRowIndex = rows.indexOf(currentRow);
        
        switch (e.key) {
            case 'ArrowUp':
                e.preventDefault();
                if (currentRowIndex > 0) {
                    const newRow = rows[currentRowIndex - 1];
                    const newCell = newRow.children[currentIndex];
                    if (newCell && newCell.classList.contains('editable-cell')) {
                        selectCell(newCell);
                    }
                }
                break;
            case 'ArrowDown':
                e.preventDefault();
                if (currentRowIndex < rows.length - 1) {
                    const newRow = rows[currentRowIndex + 1];
                    const newCell = newRow.children[currentIndex];
                    if (newCell && newCell.classList.contains('editable-cell')) {
                        selectCell(newCell);
                    }
                }
                break;
            case 'ArrowLeft':
                e.preventDefault();
                if (currentIndex > 1) { // Skip checkbox column
                    const newCell = currentRow.children[currentIndex - 1];
                    if (newCell && newCell.classList.contains('editable-cell')) {
                        selectCell(newCell);
                    }
                }
                break;
            case 'ArrowRight':
                e.preventDefault();
                if (currentIndex < currentRow.children.length - 1) {
                    const newCell = currentRow.children[currentIndex + 1];
                    if (newCell && newCell.classList.contains('editable-cell')) {
                        selectCell(newCell);
                    }
                }
                break;
            case 'Enter':
                e.preventDefault();
                if (!isEditing) {
                    startCellEditing(selectedCell);
                } else {
                    finishCellEditing();
                }
                break;
            case 'Tab':
                e.preventDefault();
                if (e.shiftKey) {
                    // Move left
                    if (currentIndex > 1) {
                        const newCell = currentRow.children[currentIndex - 1];
                        if (newCell && newCell.classList.contains('editable-cell')) {
                            selectCell(newCell);
                        }
                    }
                } else {
                    // Move right
                    if (currentIndex < currentRow.children.length - 1) {
                        const newCell = currentRow.children[currentIndex + 1];
                        if (newCell && newCell.classList.contains('editable-cell')) {
                            selectCell(newCell);
                        }
                    }
                }
                break;
            case 'Escape':
                e.preventDefault();
                if (isEditing) {
                    cancelCellEditing();
                } else {
                    clearSelection();
                }
                break;
        }
    });
}

// Setup spreadsheet toolbar
function setupSpreadsheetToolbar() {
    const deleteRowBtn = document.getElementById('delete-row-btn');
    const copyBtn = document.getElementById('copy-btn');
    const pasteBtn = document.getElementById('paste-btn');
    
    if (deleteRowBtn) {
        deleteRowBtn.addEventListener('click', function() {
            if (selectedCell) {
                const row = selectedCell.parentElement;
                if (!row) return;
                
                const tbody = row.parentElement;
                if (!tbody) return;
                
                const rowIndex = Array.from(tbody.children).indexOf(row);
                if (rowIndex >= 0) {
                    configData.splice(rowIndex, 1);
                    updateConfigTable();
                    updateSpreadsheetStatus('Row deleted');
                }
            }
        });
    }
    
    if (copyBtn) {
        copyBtn.addEventListener('click', function() {
            copySelectedRow();
        });
    }
    
    if (pasteBtn) {
        pasteBtn.addEventListener('click', function() {
            pasteToSelectedRow();
        });
    }
    
    // Keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey || e.metaKey) {
            switch (e.key) {
                case 'c':
                    e.preventDefault();
                    if (isEditing) {
                        // 편집 중일 때는 입력 필드의 텍스트를 복사
                        const input = selectedCell.querySelector('input, select, textarea');
                        if (input) {
                            input.select();
                            document.execCommand('copy');
                            updateSpreadsheetStatus('Copied from input field');
                        }
                    } else if (selectedCell) {
                        copySelectedCell();
                    } else {
                        copySelectedRow();
                    }
                    break;
                case 'v':
                    e.preventDefault();
                    if (isEditing) {
                        // 편집 중일 때는 입력 필드에 붙여넣기
                        const input = selectedCell.querySelector('input, select, textarea');
                        if (input) {
                            navigator.clipboard.readText().then(text => {
                                input.value = text;
                                updateSpreadsheetStatus('Pasted to input field');
                            }).catch(() => {
                                // 폴백
                                input.focus();
                                document.execCommand('paste');
                                updateSpreadsheetStatus('Pasted to input field');
                            });
                        }
                    } else if (selectedCell) {
                        pasteToSelectedCell();
                    } else {
                        pasteToSelectedRow();
                    }
                    break;
                case 'n':
                    e.preventDefault();
                    addConfigRow();
                    updateSpreadsheetStatus('Row added');
                    break;
            }
        }
        
        if (e.key === 'Delete' && selectedCell) {
            e.preventDefault();
            const row = selectedCell.parentElement;
            if (!row) return;
            
            const tbody = row.parentElement;
            if (!tbody) return;
            
            const rowIndex = Array.from(tbody.children).indexOf(row);
            if (rowIndex >= 0) {
                configData.splice(rowIndex, 1);
                updateConfigTable();
                updateSpreadsheetStatus('Row deleted');
            }
        }
    });
}

// Cell selection
function selectCell(cell) {
    clearSelection();
    selectedCell = cell;
    cell.classList.add('selected');
    updateSpreadsheetStatus(`Selected: ${getCellAddress(cell)}`);
}

// Clear selection
function clearSelection() {
    if (selectedCell) {
        selectedCell.classList.remove('selected');
        selectedCell = null;
    }
    updateSpreadsheetStatus('Ready');
}

// Get cell address (e.g., "A1", "B2")
function getCellAddress(cell) {
    if (!cell) return '';
    
    const row = cell.parentElement;
    if (!row) return '';
    
    const tbody = row.parentElement;
    if (!tbody) return '';
    
    const rowIndex = Array.from(tbody.children).indexOf(row) + 1;
    
    // Find the column index among editable cells only
    const editableCells = Array.from(row.children).filter(c => c.classList.contains('editable-cell'));
    const colIndex = editableCells.indexOf(cell);
    const colLetter = String.fromCharCode(65 + colIndex);
    
    return `${colLetter}${rowIndex}`;
}

// Start cell editing
function startCellEditing(cell) {
    if (isEditing) return;
    
    isEditing = true;
    cell.classList.add('editing');
    
    const cellType = cell.getAttribute('data-type');
    const currentValue = cell.textContent.trim();
    const field = cell.getAttribute('data-field');
    const index = parseInt(cell.getAttribute('data-index'));
    
    // Clear cell content
    cell.innerHTML = '';
    
    let inputElement;
    
    switch (cellType) {
        case 'select':
            const options = cell.getAttribute('data-options').split(',');
            inputElement = document.createElement('select');
            inputElement.className = 'cell-edit-input';
            options.forEach(option => {
                const optionElement = document.createElement('option');
                optionElement.value = option;
                optionElement.textContent = option;
                if (option === currentValue) {
                    optionElement.selected = true;
                }
                inputElement.appendChild(optionElement);
            });
            break;
            
        case 'textarea':
            inputElement = document.createElement('textarea');
            inputElement.className = 'cell-edit-input';
            inputElement.value = currentValue;
            inputElement.rows = 3;
            break;
            
        case 'number':
            inputElement = document.createElement('input');
            inputElement.type = 'number';
            inputElement.className = 'cell-edit-input';
            inputElement.value = currentValue;
            inputElement.step = 'any';
            break;
            
        case 'line':
            // Create input for line value only
            inputElement = document.createElement('input');
            inputElement.type = 'number';
            inputElement.className = 'cell-edit-input';
            inputElement.value = currentValue;
            inputElement.step = 'any';
            inputElement.placeholder = 'Value';
            break;
            
        case 'color':
            // Create color select dropdown with only color (no text)
            inputElement = document.createElement('select');
            inputElement.className = 'cell-edit-input color-select';
            const colors = [
                { value: '#FF0000', name: 'Red' },
                { value: '#00FF00', name: 'Green' },
                { value: '#0000FF', name: 'Blue' },
                { value: '#FF6600', name: 'Orange' },
                { value: '#9900FF', name: 'Purple' },
                { value: '#00CC00', name: 'Lime' },
                { value: '#FF00FF', name: 'Magenta' },
                { value: '#00FFFF', name: 'Cyan' },
                { value: '#FFD700', name: 'Gold' },
                { value: '#FF4500', name: 'RedOrange' },
                { value: '#8A2BE2', name: 'BlueViolet' },
                { value: '#32CD32', name: 'LimeGreen' },
                { value: '#FF1493', name: 'DeepPink' },
                { value: '#00CED1', name: 'DarkTurquoise' },
                { value: '#FF8C00', name: 'DarkOrange' },
                { value: '#9932CC', name: 'DarkOrchid' }
            ];
            const currentColor = cell.getAttribute('data-color') || '#FF0000';
            
            colors.forEach(color => {
                const option = document.createElement('option');
                option.value = color.value;
                option.textContent = '';
                option.style.backgroundColor = color.value;
                option.style.color = color.value;
                if (color.value === currentColor) {
                    option.selected = true;
                }
                inputElement.appendChild(option);
            });
            break;
            
        case 'file':
            // Create file input
            const fileInput = document.createElement('input');
            fileInput.type = 'file';
            fileInput.accept = '.py';
            fileInput.className = 'cell-edit-input';
            
            const fileLabel = document.createElement('label');
            fileLabel.textContent = currentValue === '첨부(.py)' ? 'Select .py file' : currentValue;
            fileLabel.className = 'file-input-label';
            
            cell.appendChild(fileLabel);
            cell.appendChild(fileInput);
            
            fileInput.style.display = 'none';
            fileLabel.addEventListener('click', () => fileInput.click());
            
            fileInput.addEventListener('change', function(e) {
                const file = e.target.files[0];
                if (file) {
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        const fileContent = e.target.result;
                        fileLabel.textContent = file.name;
                        
                        // 파일 내용을 configData에 저장
                        const index = parseInt(cell.getAttribute('data-index'));
                        const field = cell.getAttribute('data-field');
                        if (index >= 0 && index < configData.length) {
                            configData[index][field] = file.name;
                            configData[index]['custom_py_content'] = fileContent;
                        }
                        
                        finishCellEditing();
                    };
                    reader.readAsText(file);
                }
            });
            
            fileInput.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    cancelCellEditing();
                }
            });
            
            return;
            
        default: // text
            inputElement = document.createElement('input');
            inputElement.type = 'text';
            inputElement.className = 'cell-edit-input';
            inputElement.value = currentValue;
            break;
    }
    
    cell.appendChild(inputElement);
    inputElement.focus();
    if (cellType !== 'select' && cellType !== 'color') {
        inputElement.select();
    }
    
    // Handle input events
    inputElement.addEventListener('blur', finishCellEditing);
    inputElement.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            finishCellEditing();
        } else if (e.key === 'Escape') {
            cancelCellEditing();
        } else if (e.ctrlKey || e.metaKey) {
            // Ctrl+C, Ctrl+V 등은 상위 이벤트 핸들러에서 처리
            e.stopPropagation();
        }
    });
    
    // 편집 중일 때도 복사/붙여넣기 지원
    inputElement.addEventListener('copy', function(e) {
        e.stopPropagation();
        // 기본 복사 동작 허용
    });
    
    inputElement.addEventListener('paste', function(e) {
        e.stopPropagation();
        // 기본 붙여넣기 동작 허용
    });
    
    updateSpreadsheetStatus('Editing');
}

// Finish cell editing
function finishCellEditing() {
    if (!isEditing || !selectedCell) return;
    
    const cellType = selectedCell.getAttribute('data-type');
    const field = selectedCell.getAttribute('data-field');
    const index = parseInt(selectedCell.getAttribute('data-index'));
    
    let value = '';
    
    if (cellType === 'file') {
        const fileInput = selectedCell.querySelector('input[type="file"]');
        const fileLabel = selectedCell.querySelector('.file-input-label');
        value = fileLabel ? fileLabel.textContent : '';
        
        // 파일 내용도 함께 저장
        if (fileInput && fileInput.files[0]) {
            const reader = new FileReader();
            reader.onload = function(e) {
                const fileContent = e.target.result;
                if (index >= 0 && index < configData.length) {
                    configData[index]['custom_py_content'] = fileContent;
                }
            };
            reader.readAsText(fileInput.files[0]);
        }
    } else {
        const input = selectedCell.querySelector('input, select, textarea');
        value = input ? input.value : '';
    }
    
    // Update configData
    if (index >= 0 && index < configData.length) {
        configData[index][field] = value;
        
        // Update color field for color type
        if (cellType === 'color') {
            selectedCell.setAttribute('data-color', value);
        }
    }
    
    // Update cell display
    updateCellDisplay(selectedCell, value, cellType);
    
    // Remove editing class
    selectedCell.classList.remove('editing');
    isEditing = false;
    updateSpreadsheetStatus(`Updated: ${getCellAddress(selectedCell)}`);
}

// Update cell display
function updateCellDisplay(cell, value, cellType) {
    switch (cellType) {
        case 'line':
            cell.innerHTML = value || '';
            break;
        case 'color':
            cell.innerHTML = `
                <span class="color-indicator" style="background-color: ${value || '#FF0000'}"></span>
                ${getColorName(value) || 'Red'}
            `;
            cell.setAttribute('data-color', value || '#FF0000');
            break;
        case 'file':
            cell.innerHTML = value || '첨부(.py)';
            break;
        default:
            cell.innerHTML = value || '';
            break;
    }
}

// Cancel cell editing
function cancelCellEditing() {
    if (!isEditing || !selectedCell) return;
    
    const cellType = selectedCell.getAttribute('data-type');
    const originalValue = selectedCell.getAttribute('data-original-value') || '';
    
    // Restore original content
    updateCellDisplay(selectedCell, originalValue, cellType);
    
    selectedCell.classList.remove('editing');
    isEditing = false;
    updateSpreadsheetStatus('Edit cancelled');
}

// Get color name
function getColorName(color) {
    const colorMap = {
        '#FF0000': 'Red', '#00FF00': 'Green', '#0000FF': 'Blue',
        '#FF6600': 'Orange', '#9900FF': 'Purple', '#FF00FF': 'Magenta',
        '#00FFFF': 'Cyan', '#FFD700': 'Gold', '#FF4500': 'RedOrange',
        '#8A2BE2': 'BlueViolet', '#32CD32': 'LimeGreen', '#FF1493': 'DeepPink',
        '#00CED1': 'DarkTurquoise', '#FF8C00': 'DarkOrange', '#00CC00': 'Lime'
    };
    return colorMap[color] || color;
}

// Get contrast color (black or white) for better text visibility
function getContrastColor(hexColor) {
    // Remove # if present
    const hex = hexColor.replace('#', '');
    
    // Convert to RGB
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    
    // Calculate luminance
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    
    // Return black for light colors, white for dark colors
    return luminance > 0.5 ? '#000000' : '#FFFFFF';
}

// Copy selected cell
function copySelectedCell() {
    if (!selectedCell) return;
    
    const cellType = selectedCell.getAttribute('data-type');
    let value = '';
    
    if (cellType === 'color') {
        // 색상 셀의 경우 색상 값만 복사
        value = selectedCell.getAttribute('data-color') || '';
    } else {
        // 일반 셀의 경우 텍스트 내용 복사
        value = selectedCell.textContent.trim();
    }
    
    // 클립보드에 복사
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(value).then(() => {
            updateSpreadsheetStatus('Copied to clipboard');
        }).catch(err => {
            console.error('Failed to copy to clipboard:', err);
            // 폴백: 전역 변수에 저장
            window.clipboardData = value;
            updateSpreadsheetStatus('Copied to clipboard (fallback)');
        });
    } else {
        // 폴백: 전역 변수에 저장
        window.clipboardData = value;
        updateSpreadsheetStatus('Copied to clipboard (fallback)');
    }
}

// Paste to selected cell
function pasteToSelectedCell() {
    if (!selectedCell) return;
    
    const cellType = selectedCell.getAttribute('data-type');
    const field = selectedCell.getAttribute('data-field');
    const index = parseInt(selectedCell.getAttribute('data-index'));
    
    // 클립보드에서 데이터 가져오기
    const getClipboardData = async () => {
        if (navigator.clipboard && window.isSecureContext) {
            try {
                return await navigator.clipboard.readText();
            } catch (err) {
                console.error('Failed to read from clipboard:', err);
                return window.clipboardData || '';
            }
        } else {
            return window.clipboardData || '';
        }
    };
    
    getClipboardData().then(value => {
        if (!value) {
            updateSpreadsheetStatus('No data to paste');
            return;
        }
        
        // Update configData
        if (index >= 0 && index < configData.length) {
            configData[index][field] = value;
        }
        
        // Update cell display
        updateCellDisplay(selectedCell, value, cellType);
        
        updateSpreadsheetStatus('Pasted from clipboard');
    });
}

// Update spreadsheet status
function updateSpreadsheetStatus(message) {
    const statusElement = document.getElementById('spreadsheet-status');
    if (statusElement) {
        statusElement.textContent = message;
    }
}





// Row-based copy
function copySelectedRow() {
    const selectedRow = document.querySelector('.row-selected');
    if (!selectedRow) {
        showNotification('Please select a row to copy.', 'error');
        return;
    }
    const index = parseInt(selectedRow.getAttribute('data-index'));
    window.copiedRowData = { ...configData[index] };
    showNotification('Row copied!');
}

// Row-based paste
function pasteToSelectedRow() {
    if (!window.copiedRowData) {
        showNotification('No copied row data.', 'error');
        return;
    }
    const selectedRow = document.querySelector('.row-selected');
    if (!selectedRow) {
        showNotification('Select a row to paste.', 'error');
        return;
    }
    const rowIndex = parseInt(selectedRow.getAttribute('data-index'));
    if (rowIndex < 0 || rowIndex >= configData.length) return;
    Object.keys(window.copiedRowData).forEach(key => {
        if (key !== 'parameter_name') {
            configData[rowIndex][key] = window.copiedRowData[key];
        }
    });
    updateConfigTable();
    showNotification('Row pasted!');
}

// Canvas Mode Functions
function toggleCanvasMode() {
    if (typeof GridStack === 'undefined' || typeof echarts === 'undefined') {
        showNotification('Canvas mode requires the optional ECharts/GridStack libraries.', 'error');
        return;
    }
    isCanvasMode = !isCanvasMode;
    const canvasBtn = document.getElementById('canvas-btn');
    const plotArea = document.getElementById('plot-area');
    const canvasArea = document.getElementById('canvas-area');
    
    if (isCanvasMode) {
        canvasBtn.classList.add('primary');
        plotArea.style.display = 'none';
        canvasArea.style.display = 'block';
        
        // Initialize GridStack if not already initialized
        if (!gridStack) {
            gridStack = GridStack.init({
                cellHeight: 100,
                margin: 5,
                float: true,
                disableOneColumnMode: true,
                acceptWidgets: true,
                draggable: { handle: '.drag-handle' }
            }, canvasArea);
            
            // Handle resize events for ECharts
            gridStack.on('resizestop', function(event, el) {
                const content = el.querySelector('.grid-stack-item-content');
                const chartDiv = content.querySelector('.echarts-container');
                if (chartDiv) {
                    const chart = echarts.getInstanceByDom(chartDiv);
                    if (chart) chart.resize();
                }
            });
        }
    } else {
        canvasBtn.classList.remove('primary');
        plotArea.style.display = 'grid';
        canvasArea.style.display = 'none';
        updateGridLayout();
    }
}

function addCanvasChart() {
    if (!gridStack || typeof echarts === 'undefined') return;
    
    const widgetId = `widget-${Date.now()}`;
    const chartId = `echart-${Date.now()}`;
    
    const widgetHtml = `
        <div class="grid-stack-item" gs-w="6" gs-h="4">
            <div class="grid-stack-item-content" style="background: white; border: 1px solid #ccc; border-radius: 4px; padding: 10px; display: flex; flex-direction: column; overflow: hidden;">
                <div class="drag-handle" style="cursor: move; padding: 5px; background: #f5f5f5; border-bottom: 1px solid #eee; margin: -10px -10px 10px -10px; border-radius: 4px 4px 0 0; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: bold; font-size: 12px;">Canvas Chart</span>
                    <div style="display: flex; align-items: center;">
                        <label style="font-size: 12px; margin-right: 10px; display: flex; align-items: center; cursor: pointer;" title="Enable/Disable Dragging">
                            <input type="checkbox" class="move-toggle" checked style="margin-right: 4px;"> Move/Zoom
                        </label>
                        <button class="reset-zoom-btn" style="border: none; background: none; cursor: pointer; color: #666; font-size: 14px; margin-right: 5px;" title="Reset Zoom">⟲</button>
                        <button class="settings-widget-btn" style="border: none; background: none; cursor: pointer; color: #666; font-size: 14px; margin-right: 5px;" title="Settings">⚙️</button>
                        <button class="remove-widget-btn" style="border: none; background: none; cursor: pointer; color: #999; font-size: 16px;" title="Remove">&times;</button>
                    </div>
                </div>
                <div id="${chartId}" class="echarts-container" style="flex: 1; width: 100%; min-height: 0;"></div>
            </div>
        </div>
    `;
    
    const el = gridStack.addWidget(widgetHtml);
    
    // Handle Move Toggle
    const moveToggle = el.querySelector('.move-toggle');
    if (moveToggle) {
        moveToggle.addEventListener('change', (e) => {
            const isMovable = e.target.checked;
            gridStack.update(el, { noMove: !isMovable });
            
            const dragHandle = el.querySelector('.drag-handle');
            if (dragHandle) {
                dragHandle.style.cursor = isMovable ? 'move' : 'default';
                dragHandle.style.backgroundColor = isMovable ? '#f5f5f5' : '#e9e9e9';
            }

            // Toggle Zoom based on Move state (Move checked -> Zoom disabled)
            const chartContainer = el.querySelector(`#${chartId}`);
            if (chartContainer) {
                const chart = echarts.getInstanceByDom(chartContainer);
                if (chart) {
                    chart.setOption({
                        dataZoom: [
                            { id: 'zoomX', disabled: isMovable },
                            { id: 'zoomY', disabled: isMovable }
                        ]
                    });
                }
            }
        });
        // Prevent drag start when clicking the checkbox
        moveToggle.addEventListener('mousedown', (e) => e.stopPropagation());
    }

    // Handle Reset Zoom Button
    const resetZoomBtn = el.querySelector('.reset-zoom-btn');
    if (resetZoomBtn) {
        resetZoomBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const chartContainer = el.querySelector(`#${chartId}`);
            if (chartContainer) {
                const chart = echarts.getInstanceByDom(chartContainer);
                if (chart) {
                    chart.dispatchAction({
                        type: 'dataZoom',
                        batch: [
                            { dataZoomId: 'zoomX', start: 0, end: 100 },
                            { dataZoomId: 'zoomY', start: 0, end: 100 }
                        ]
                    });
                }
            }
        });
    }

    // Initialize ECharts after DOM update
    setTimeout(() => {
        const chartContainer = el.querySelector(`#${chartId}`);
        if (chartContainer) {
            const myChart = echarts.init(chartContainer);
            
            // Default empty option or sample data
            const option = {
                title: { text: 'New Chart', left: 'center', top: 'center', textStyle: { color: '#ccc' } },
                tooltip: { trigger: 'axis' },
                grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
                xAxis: { type: 'category', boundaryGap: false, data: [] },
                yAxis: { type: 'value' },
                series: [],
                // Default Zoom settings
                dataZoom: [
                    { type: 'inside', xAxisIndex: 0, disabled: true, id: 'zoomX' },
                    { type: 'inside', yAxisIndex: 0, disabled: true, id: 'zoomY' }
                ]
            };
            myChart.setOption(option);
            
            // Handle remove button
            const removeBtn = el.querySelector('.remove-widget-btn');
            if (removeBtn) {
                removeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    gridStack.removeWidget(el);
                    myChart.dispose();
                });
            }

            // Handle settings button
            const settingsBtn = el.querySelector('.settings-widget-btn');
            if (settingsBtn) {
                settingsBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openCanvasSettings(chartId);
                });
            }
            
            // Add Drop Event Listeners for Parameter Visualization
            chartContainer.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
                chartContainer.style.backgroundColor = '#f0f8ff';
                chartContainer.style.border = '2px dashed #2196F3';
            });

            chartContainer.addEventListener('dragleave', (e) => {
                chartContainer.style.backgroundColor = '';
                chartContainer.style.border = 'none';
            });

            chartContainer.addEventListener('drop', async (e) => {
                e.preventDefault();
                chartContainer.style.backgroundColor = '';
                chartContainer.style.border = 'none';
                const paramName = e.dataTransfer.getData('text/plain');
                
                if (paramName) {
                    myChart.showLoading();
                    try {
                        // Fetch full data
                        const data = await fetchChartData(paramName, -Infinity, Infinity);
                        
                        if (data.time && data.value) {
                            const seriesData = [];
                            const len = Math.min(data.time.length, data.value.length);
                            for (let i = 0; i < len; i++) {
                                seriesData.push([data.time[i], data.value[i]]);
                            }
                            
                            const currentOption = myChart.getOption();
                            const isInitial = !currentOption || !currentOption.series || currentOption.series.length === 0 || (currentOption.title && currentOption.title[0] && currentOption.title[0].text === 'New Chart');
                            
                            const newSeries = {
                                name: paramName,
                                type: 'line',
                                showSymbol: false,
                                sampling: 'lttb',
                                data: seriesData
                            };

                            if (isInitial) {
                                const option = {
                                    title: { 
                                        text: paramName, 
                                        left: 'center', 
                                        top: 5,
                                        textStyle: { fontSize: 14, color: '#333' }
                                    },
                                    tooltip: { 
                                        trigger: 'axis',
                                        axisPointer: { type: 'cross' }
                                    },
                                    legend: { data: [paramName], top: 30 },
                                    grid: { left: '5%', right: '5%', bottom: '10%', top: '20%', containLabel: true },
                                    xAxis: { type: 'value', scale: true, splitLine: { show: false } },
                                    yAxis: { type: 'value', scale: true },
                                    series: [newSeries],
                                    animation: false
                                };
                                myChart.setOption(option, true);
                            } else {
                                const existingSeries = currentOption.series;
                                if (existingSeries.some(s => s.name === paramName)) return;
                                
                                let currentTitle = currentOption.title[0].text;
                                if (currentTitle.length < 50) currentTitle += ' vs ' + paramName;
                                else if (!currentTitle.includes('...')) currentTitle += '...';
                                
                                existingSeries.push(newSeries);
                                const legendData = existingSeries.map(s => s.name);
                                
                                myChart.setOption({
                                    title: { text: currentTitle },
                                    legend: { data: legendData },
                                    series: existingSeries
                                }, false);
                            }
                        }
                    } catch (err) {
                        console.error('Error loading canvas chart data:', err);
                    } finally {
                        myChart.hideLoading();
                    }
                }
            });

            // Resize observer for auto resizing
            new ResizeObserver(() => {
                myChart.resize();
            }).observe(chartContainer);
        }
    }, 50);
}

// Canvas Chart Settings Functions
function openCanvasSettings(chartId) {
    const chartDiv = document.getElementById(chartId);
    if (!chartDiv) return;
    
    const chart = echarts.getInstanceByDom(chartDiv);
    if (!chart) return;
    
    const opt = chart.getOption();
    
    // Set current values in modal
    document.getElementById('canvas-setting-chart-id').value = chartId;
    
    // Zoom settings
    // Hide Zoom settings in modal as they are now controlled by the header toggle
    const zoomX = document.getElementById('canvas-zoom-x');
    const zoomY = document.getElementById('canvas-zoom-y');
    if (zoomX && zoomX.parentElement) zoomX.parentElement.style.display = 'none';
    if (zoomY && zoomY.parentElement) zoomY.parentElement.style.display = 'none';
    
    // Legend settings
    const legend = (Array.isArray(opt.legend) ? opt.legend[0] : opt.legend) || {};
    document.getElementById('canvas-legend-show').checked = legend.show !== false;
    document.getElementById('canvas-legend-scroll').checked = legend.type === 'scroll';
    document.getElementById('canvas-legend-orient').value = legend.orient || 'horizontal';
    
    // Determine position and placement
    // Simple heuristic: if grid has large margin, assume 'outside'
    // But for simplicity, we just read the legend pos properties
    let posMain = 'top';
    let posAlign = 'center';
    
    if (legend.bottom !== undefined && legend.bottom !== 'auto') posMain = 'bottom';
    else if (legend.left !== undefined && legend.left !== 'auto' && legend.orient === 'vertical') posMain = 'left';
    else if (legend.right !== undefined && legend.right !== 'auto' && legend.orient === 'vertical') posMain = 'right';
    
    if (posMain === 'top' || posMain === 'bottom') {
        if (legend.left === 'left') posAlign = 'start';
        else if (legend.left === 'right') posAlign = 'end';
        else posAlign = 'center';
    } else {
        if (legend.top === 'top') posAlign = 'start';
        else if (legend.top === 'bottom') posAlign = 'end';
        else posAlign = 'center';
    }
    
    document.getElementById('canvas-legend-pos-main').value = posMain;
    document.getElementById('canvas-legend-pos-align').value = posAlign;
    
    // Check grid to guess placement (inside/outside)
    // This is a bit loose, but we default to 'inside' unless we stored metadata.
    // For now, default to 'inside' in UI unless user changes it.
    document.getElementById('canvas-legend-placement').value = 'inside'; 

    document.getElementById('canvas-settings-modal').style.display = 'flex';
}

function applyCanvasSettings() {
    const chartId = document.getElementById('canvas-setting-chart-id').value;
    const chartDiv = document.getElementById(chartId);
    if (!chartDiv) return;
    const chart = echarts.getInstanceByDom(chartDiv);
    if (!chart) return;

    const showLegend = document.getElementById('canvas-legend-show').checked;
    const scrollLegend = document.getElementById('canvas-legend-scroll').checked;
    const orient = document.getElementById('canvas-legend-orient').value;
    const placement = document.getElementById('canvas-legend-placement').value;
    const posMain = document.getElementById('canvas-legend-pos-main').value;
    const posAlign = document.getElementById('canvas-legend-pos-align').value;

    // Construct Legend
    const legend = {
        show: showLegend,
        type: scrollLegend ? 'scroll' : 'plain',
        orient: orient,
        left: 'auto', top: 'auto', right: 'auto', bottom: 'auto'
    };

    // Map position inputs to ECharts properties
    if (posMain === 'top') { legend.top = 'top'; legend.left = posAlign === 'start' ? 'left' : (posAlign === 'end' ? 'right' : 'center'); }
    else if (posMain === 'bottom') { legend.bottom = 'bottom'; legend.left = posAlign === 'start' ? 'left' : (posAlign === 'end' ? 'right' : 'center'); }
    else if (posMain === 'left') { legend.left = 'left'; legend.top = posAlign === 'start' ? 'top' : (posAlign === 'end' ? 'bottom' : 'middle'); }
    else if (posMain === 'right') { legend.right = 'right'; legend.top = posAlign === 'start' ? 'top' : (posAlign === 'end' ? 'bottom' : 'middle'); }

    // Adjust Grid for 'Outside' placement
    const grid = { containLabel: true, left: '3%', right: '4%', top: 60, bottom: '3%' }; // Reset to default-ish
    if (placement === 'outside' && showLegend) {
        if (posMain === 'top') grid.top = 80; // More space at top
        else if (posMain === 'bottom') grid.bottom = 60;
        else if (posMain === 'left') grid.left = 120;
        else if (posMain === 'right') grid.right = 120;
    }

    chart.setOption({
        legend: legend,
        grid: grid
    });

    document.getElementById('canvas-settings-modal').style.display = 'none';
}

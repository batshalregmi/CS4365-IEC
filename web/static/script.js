// State
let currentTable = null;
let currentPage = 1;
let totalPages = 1;

// DOM Elements
const tableList = document.getElementById('table-list');
const tableInfo = document.getElementById('table-info');
const dataContainer = document.getElementById('data-container');
const currentTableName = document.getElementById('current-table-name');
const dataTable = document.getElementById('data-table');
const pageInfo = document.getElementById('page-info');
const rowInfo = document.getElementById('row-info');
const prevPageBtn = document.getElementById('prev-page');
const nextPageBtn = document.getElementById('next-page');
const queryInput = document.getElementById('query-input');
const runQueryBtn = document.getElementById('run-query');
const queryResults = document.getElementById('query-results');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadTables();
    setupTabs();
    setupPagination();
    setupQuery();
});

// Load tables list
async function loadTables() {
    try {
        const response = await fetch('/api/tables');
        const tables = await response.json();
        
        tableList.innerHTML = '';
        
        if (tables.length === 0) {
            tableList.innerHTML = '<p class="placeholder">No tables found</p>';
            return;
        }
        
        tables.forEach(table => {
            const item = document.createElement('div');
            item.className = 'table-item';
            item.textContent = table;
            item.addEventListener('click', () => selectTable(table));
            tableList.appendChild(item);
        });
    } catch (error) {
        tableList.innerHTML = `<p class="error-message">Error loading tables: ${error.message}</p>`;
    }
}

// Select a table
async function selectTable(tableName) {
    // Update UI
    document.querySelectorAll('.table-item').forEach(item => {
        item.classList.toggle('active', item.textContent === tableName);
    });
    
    currentTable = tableName;
    currentPage = 1;
    
    tableInfo.classList.add('hidden');
    dataContainer.classList.remove('hidden');
    currentTableName.textContent = tableName;
    
    await loadTableData();
}

// Load table data
async function loadTableData() {
    if (!currentTable) return;
    
    try {
        const response = await fetch(`/api/table/${currentTable}/data?page=${currentPage}&per_page=100`);
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        // Update pagination
        totalPages = data.total_pages;
        pageInfo.textContent = `Page ${data.page} of ${totalPages}`;
        prevPageBtn.disabled = currentPage <= 1;
        nextPageBtn.disabled = currentPage >= totalPages;
        
        // Update row info
        const startRow = (currentPage - 1) * data.per_page + 1;
        const endRow = Math.min(startRow + data.rows.length - 1, data.total);
        rowInfo.textContent = `Showing rows ${startRow}-${endRow} of ${data.total.toLocaleString()} total (${data.columns.length} columns)`;
        
        // Render table
        renderTable(data.columns, data.rows);
        
    } catch (error) {
        dataTable.innerHTML = `<tr><td class="error-message">Error: ${error.message}</td></tr>`;
    }
}

// Render table data
function renderTable(columns, rows) {
    const thead = dataTable.querySelector('thead');
    const tbody = dataTable.querySelector('tbody');
    
    // Header
    thead.innerHTML = '<tr>' + columns.map(col => `<th title="${col}">${col}</th>`).join('') + '</tr>';
    
    // Body
    tbody.innerHTML = rows.map(row => 
        '<tr>' + row.map(cell => `<td title="${escapeHtml(String(cell ?? ''))}">${escapeHtml(String(cell ?? ''))}</td>`).join('') + '</tr>'
    ).join('');
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Setup tabs
function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // Update tab content
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.toggle('active', content.id === `${tabName}-tab`);
            });
        });
    });
}

// Setup pagination
function setupPagination() {
    prevPageBtn.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            loadTableData();
        }
    });
    
    nextPageBtn.addEventListener('click', () => {
        if (currentPage < totalPages) {
            currentPage++;
            loadTableData();
        }
    });
}

// Setup query
function setupQuery() {
    runQueryBtn.addEventListener('click', runQuery);
    
    queryInput.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
            runQuery();
        }
    });
}

// Run custom query
async function runQuery() {
    const query = queryInput.value.trim();
    
    if (!query) {
        queryResults.innerHTML = '<p class="placeholder">Enter a query to run</p>';
        return;
    }
    
    queryResults.innerHTML = '<p class="loading">Running query...</p>';
    
    try {
        const response = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });
        
        const data = await response.json();
        
        if (data.error) {
            queryResults.innerHTML = `<div class="error-message">${escapeHtml(data.error)}</div>`;
            return;
        }
        
        let html = '';
        
        if (data.truncated) {
            html += '<div class="truncated-warning">Results truncated to 1000 rows</div>';
        }
        
        html += '<table class="result-table">';
        html += '<thead><tr>' + data.columns.map(col => `<th>${escapeHtml(col)}</th>`).join('') + '</tr></thead>';
        html += '<tbody>';
        html += data.rows.map(row => 
            '<tr>' + row.map(cell => `<td title="${escapeHtml(String(cell ?? ''))}">${escapeHtml(String(cell ?? ''))}</td>`).join('') + '</tr>'
        ).join('');
        html += '</tbody></table>';
        
        queryResults.innerHTML = html;
        
    } catch (error) {
        queryResults.innerHTML = `<div class="error-message">Error: ${escapeHtml(error.message)}</div>`;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    // Get the search input element
    const searchInput = document.querySelector('.search-input');
    
    // If search input exists, add event listeners
    if (searchInput) {
        // Add input event listener for real-time search
        searchInput.addEventListener('input', function(e) {
            const searchTerm = e.target.value.toLowerCase();
            filterTableRows(searchTerm);
        });
        
        // Add keydown event listener for Enter key
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const searchTerm = e.target.value.toLowerCase();
                filterTableRows(searchTerm);
            }
        });
    }

    // Function to filter table rows based on search term
    function filterTableRows(searchTerm) {
        const table = document.querySelector('table');
        if (!table) return;

        const rows = table.querySelectorAll('tbody tr');
        let hasResults = false;

        rows.forEach(row => {
            // Get all cell content in the row
            const rowText = Array.from(row.cells)
                .map(cell => cell.textContent.toLowerCase())
                .join(' ');

            // Show/hide row based on search term
            if (rowText.includes(searchTerm)) {
                row.style.display = '';
                hasResults = true;
            } else {
                row.style.display = 'none';
            }
        });

        // Show/hide no results message
        const noResultsRow = document.getElementById('no-results-message');
        if (noResultsRow) {
            noResultsRow.style.display = hasResults || searchTerm === '' ? 'none' : 'table-row';
        }
    }
});

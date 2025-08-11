odoo.define('library_management.book_chart', function (require) {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        const ctx = document.getElementById('doughnutChart');
        if (!ctx) return;

        // Dummy data (replace with real data later)
        const data = {
            labels: ['Fiction', 'Non-Fiction', 'Sci-Fi'],
            datasets: [{
                data: [12, 19, 7],
                backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56'],
            }]
        };

        new Chart(ctx, {
            type: 'doughnut',
            data: data,
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    });
});

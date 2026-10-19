// Counter plugin: the - and + buttons change the number input beside them,
// then fire the events annotation.js listens for, so the value saves like
// any typed number.
(function () {
    function clamp(input, value) {
        var min = input.min === '' ? -Infinity : Number(input.min);
        var max = input.max === '' ? Infinity : Number(input.max);
        return Math.min(max, Math.max(min, value));
    }

    document.addEventListener('click', function (event) {
        var button = event.target.closest('.counter-plugin-step');
        if (!button) return;
        var row = button.closest('.counter-plugin-row');
        var input = row.querySelector('.counter-plugin-value');
        var current = input.value === '' ? Number(row.dataset.start || 0) : Number(input.value);
        input.value = String(clamp(input, current + Number(button.dataset.delta)));
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    });
})();

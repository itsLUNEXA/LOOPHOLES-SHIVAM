document.addEventListener('DOMContentLoaded', function () {
  // Free / Paid pricing toggle
  const isFreeCheckbox = document.getElementById('id_is_free');
  const priceInput = document.getElementById('id_price');

  if (isFreeCheckbox && priceInput) {
    const priceGroup = priceInput.closest('.price-wrapper') || priceInput.closest('.mb-3');
    function updatePriceVisibility() {
      if (isFreeCheckbox.checked) {
        if (priceGroup) priceGroup.style.display = 'none';
        priceInput.value = '';
        priceInput.removeAttribute('required');
      } else {
        if (priceGroup) priceGroup.style.display = 'block';
        priceInput.setAttribute('required', 'required');
      }
    }
    isFreeCheckbox.addEventListener('change', updatePriceVisibility);
    updatePriceVisibility();
  }

  // Auto-dismiss alerts after 6 seconds
  const autoAlerts = document.querySelectorAll('.alert-dismissible');
  autoAlerts.forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    }, 6000);
  });

  // Image preview before upload
  const fileInputs = document.querySelectorAll('input[type="file"][accept*="image"]');
  fileInputs.forEach(function (input) {
    input.addEventListener('change', function () {
      const file = this.files[0];
      if (file) {
        if (file.size > 5 * 1024 * 1024) {
          alert('File size exceeds 5MB limit. Please choose a smaller image.');
          this.value = '';
          return;
        }
      }
    });
  });

  // Copy event link to clipboard
  const copyBtn = document.getElementById('copyEventLinkBtn');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      navigator.clipboard.writeText(window.location.href).then(function () {
        const originalText = copyBtn.innerHTML;
        copyBtn.innerHTML = '<i class="bi bi-check2"></i> Copied!';
        setTimeout(function () {
          copyBtn.innerHTML = originalText;
        }, 2000);
      });
    });
  }
});

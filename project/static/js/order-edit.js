(() => {
  const form = document.getElementById('editOrderForm');
  if (!form) return;

  const productSelect = document.getElementById('newProductSelect');
  const quantityInput = document.getElementById('newProductQuantity');
  const addonChoices = document.getElementById('editAddonChoices');
  const addButton = document.getElementById('queueOrderItem');
  const queuedItems = document.getElementById('queuedOrderItems');
  const additionsInput = document.getElementById('additionsJson');
  const errorMessage = document.getElementById('editOrderError');
  const currencySymbol = (form.dataset.currency || 'BDT ').replace(/[&<>"']/g, '');
  const additions = [];

  const money = (value) => `${currencySymbol}${Number(value || 0).toLocaleString('en-BD', {minimumFractionDigits:2, maximumFractionDigits:2})}`;

  function selectedProduct() {
    const option = productSelect.selectedOptions[0];
    if (!option || !option.value) return null;
    return {
      id: Number(option.value),
      name: option.dataset.name || option.textContent.trim(),
      price: Number(option.dataset.price || 0),
      stock: Number(option.dataset.stock || 0),
      addons: JSON.parse(option.dataset.addons || '[]')
    };
  }

  function renderAddonChoices() {
    const product = selectedProduct();
    addonChoices.replaceChildren();
    addonChoices.hidden = !product || product.addons.length === 0;
    if (!product || !product.addons.length) return;

    const heading = document.createElement('span');
    heading.className = 'edit-addon-heading';
    heading.textContent = 'Optional extras';
    addonChoices.append(heading);
    product.addons.forEach((addon) => {
      const label = document.createElement('label');
      label.className = 'edit-addon-choice';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.dataset.addonId = String(addon.id);
      const text = document.createElement('span');
      const name = document.createElement('b');
      name.textContent = addon.name;
      const details = document.createElement('small');
      details.textContent = `+ ${money(addon.price)} - uses ${addon.amount} ${addon.unit}`;
      text.append(name, details);
      label.append(input, text);
      addonChoices.append(label);
    });
  }

  function renderQueuedItems() {
    queuedItems.replaceChildren();
    queuedItems.hidden = additions.length === 0;
    additions.forEach((addition, index) => {
      const row = document.createElement('div');
      row.className = 'queued-order-item';
      const info = document.createElement('div');
      const name = document.createElement('b');
      name.textContent = `${addition.quantity} x ${addition.name}`;
      info.append(name);
      if (addition.addonNames.length) {
        const extras = document.createElement('small');
        extras.textContent = `Extras: ${addition.addonNames.join(', ')}`;
        info.append(extras);
      }
      const total = document.createElement('strong');
      total.textContent = money((addition.price + addition.addonPrice) * addition.quantity);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'queued-item-remove';
      remove.textContent = 'Remove';
      remove.setAttribute('aria-label', `Remove ${addition.name} from additions`);
      remove.addEventListener('click', () => {
        additions.splice(index, 1);
        renderQueuedItems();
      });
      row.append(info, total, remove);
      queuedItems.append(row);
    });
    additionsInput.value = JSON.stringify(additions.map((addition) => ({
      id: addition.id,
      quantity: addition.quantity,
      addons: addition.addonIds
    })));
  }

  productSelect.addEventListener('change', () => {
    renderAddonChoices();
    addButton.disabled = !selectedProduct();
  });

  addButton.addEventListener('click', () => {
    const product = selectedProduct();
    const quantity = Number(quantityInput.value);
    if (!product || !Number.isInteger(quantity) || quantity < 1 || quantity > 999) return;
    const selected = [...addonChoices.querySelectorAll('input:checked')]
      .map((input) => product.addons.find((addon) => Number(addon.id) === Number(input.dataset.addonId)))
      .filter(Boolean);
    const addonIds = selected.map((addon) => Number(addon.id));
    const existing = additions.find((item) => item.id === product.id
      && item.addonIds.length === addonIds.length
      && item.addonIds.every((id, index) => id === addonIds[index]));
    if (existing && existing.quantity + quantity > 999) {
      if (errorMessage) errorMessage.textContent = 'A product quantity cannot exceed 999.';
      return;
    }
    if (existing) existing.quantity += quantity;
    else additions.push({
      id: product.id,
      name: product.name,
      price: product.price,
      quantity,
      addonIds,
      addonNames: selected.map((addon) => addon.name),
      addonPrice: selected.reduce((sum, addon) => sum + Number(addon.price), 0)
    });
    addonChoices.querySelectorAll('input').forEach((input) => { input.checked = false; });
    quantityInput.value = '1';
    if (errorMessage) errorMessage.textContent = '';
    renderQueuedItems();
  });

  form.querySelectorAll('[data-remove-line]').forEach((input) => {
    input.addEventListener('change', () => {
      input.closest('.edit-order-line')?.classList.toggle('is-removed', input.checked);
      if (errorMessage) errorMessage.textContent = '';
    });
  });

  form.addEventListener('submit', (event) => {
    const keptLine = [...form.querySelectorAll('[data-remove-line]')].some((input) => !input.checked);
    if (!keptLine && additions.length === 0) {
      event.preventDefault();
      if (errorMessage) errorMessage.textContent = 'Keep at least one item on the order.';
      return;
    }
    additionsInput.value = JSON.stringify(additions.map((addition) => ({
      id: addition.id,
      quantity: addition.quantity,
      addons: addition.addonIds
    })));
  });
})();

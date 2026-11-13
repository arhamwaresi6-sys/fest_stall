(() => {
  const cart = new Map();
  const cartItems = document.getElementById('cartItems');
  if (!cartItems) return;
  const paymentRows = document.getElementById('paymentRows');
  const addonDialog = document.getElementById('addonDialog');
  const addonChoices = document.getElementById('addonChoices');
  const addonMessage = document.getElementById('addonStockMessage');
  const confirmAddons = document.getElementById('confirmAddons');
  const checkoutForm = document.getElementById('checkoutForm');
  const bkashQrDialog = document.getElementById('bkashQrDialog');
  const couponInput = document.getElementById('couponInput');
  const couponStatus = document.getElementById('couponStatus');
  const couponCodeInput = document.getElementById('couponCode');
  let appliedCoupon = null;
  let checkingCoupon = false;
  const currency = (number) => (document.body.dataset.currency || '৳').replace(/[&<>"']/g, '') + Number(number || 0).toLocaleString('en-BD', {minimumFractionDigits:2, maximumFractionDigits:2});
  const esc = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let pendingProduct = null;
  let paymentPickerId = 0;

  const addPaymentRow = (method = 'hand') => {
    const row = document.createElement('div');
    row.className = 'payment-input-row';
    const optionsId = `payment-method-options-${++paymentPickerId}`;
    row.innerHTML = `<div class="payment-method-picker"><select class="payment-method-value" aria-hidden="true" tabindex="-1"><option value="hand">By hand (cash)</option><option value="bkash">bKash</option></select><button class="payment-method-trigger" type="button" aria-label="Payment method" aria-haspopup="listbox" aria-expanded="false" aria-controls="${optionsId}"><span class="payment-method-icon" aria-hidden="true"></span><span class="payment-method-label"></span><svg class="payment-method-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg></button><div class="payment-method-options" id="${optionsId}" role="listbox" aria-label="Payment methods" hidden><button type="button" class="payment-method-option" role="option" data-method="hand">By hand (cash)</button><button type="button" class="payment-method-option" role="option" data-method="bkash">bKash</button></div></div><div class="bkash-payment-details" hidden><div class="bkash-payment-copy"><span class="bkash-brand"><img src="${esc(checkoutForm.dataset.bkashIcon)}" alt=""> <span>bKash</span></span><b>Scan to pay</b><p>Open your bKash app and scan this QR code, or send money to the number below.</p><span class="bkash-number-label">bKash number</span><strong>01978327028</strong><small>Confirm the recipient before sending your payment.</small></div><div class="bkash-qr-frame"><button class="bkash-qr-zoom" type="button" aria-label="Enlarge bKash QR code for scanning"><img class="bkash-qr" src="${esc(checkoutForm.dataset.bkashQr)}" alt=""><span class="bkash-qr-expand-hint">Tap to enlarge</span></button><span>Scan with bKash</span></div></div>`;
    const select = row.querySelector('select');
    const methodPicker = row.querySelector('.payment-method-picker');
    const methodTrigger = row.querySelector('.payment-method-trigger');
    const methodOptions = row.querySelector('.payment-method-options');
    const optionButtons = [...methodOptions.querySelectorAll('.payment-method-option')];
    select.value = method;
    const clearFixedMenu = () => {
      methodOptions.hidden = true;
      methodOptions.classList.remove('is-fixed', 'is-open-menu');
      methodOptions.style.position = '';
      methodOptions.style.left = '';
      methodOptions.style.right = '';
      methodOptions.style.top = '';
      methodOptions.style.bottom = '';
      methodOptions.style.width = '';
      methodOptions.style.maxHeight = '';
      methodOptions.style.zIndex = '';
      methodOptions.style.display = '';
      if (methodOptions.parentElement !== methodPicker) methodPicker.append(methodOptions);
    };
    const placeFixedMenu = () => {
      if (methodOptions.parentElement !== document.body) document.body.append(methodOptions);
      methodOptions.hidden = false;
      methodOptions.classList.add('is-fixed', 'is-open-menu');
      methodOptions.style.display = 'grid';
      const rect = methodTrigger.getBoundingClientRect();
      const viewportPadding = 12;
      const gap = 6;
      const menuHeight = Math.min(methodOptions.scrollHeight || 120, 200);
      const spaceAbove = Math.max(0, rect.top - viewportPadding - gap);
      const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - viewportPadding - gap);
      const opensUp = spaceBelow < menuHeight && spaceAbove > spaceBelow;
      const availableHeight = Math.max(opensUp ? spaceAbove : spaceBelow, 96);
      const width = Math.min(Math.max(rect.width, 140), Math.max(0, window.innerWidth - viewportPadding * 2));
      const left = Math.max(viewportPadding, Math.min(rect.left, window.innerWidth - width - viewportPadding));
      methodOptions.style.position = 'fixed';
      methodOptions.style.left = `${left}px`;
      methodOptions.style.width = `${width}px`;
      methodOptions.style.right = 'auto';
      methodOptions.style.maxHeight = `${Math.min(menuHeight, availableHeight)}px`;
      methodOptions.style.zIndex = '80';
      if (opensUp) {
        methodOptions.style.top = 'auto';
        methodOptions.style.bottom = `${window.innerHeight - rect.top + gap}px`;
      } else {
        methodOptions.style.top = `${rect.bottom + gap}px`;
        methodOptions.style.bottom = 'auto';
      }
    };
    const closeMethodPicker = (restoreFocus = false) => {
      methodPicker.classList.remove('is-open');
      methodTrigger.setAttribute('aria-expanded', 'false');
      clearFixedMenu();
      if (restoreFocus) methodTrigger.focus();
    };
    const openMethodPicker = (focusSelected = false) => {
      document.querySelectorAll('.payment-method-picker.is-open').forEach((picker) => {
        if (picker === methodPicker) return;
        picker.classList.remove('is-open');
        picker.querySelector('.payment-method-trigger')?.setAttribute('aria-expanded', 'false');
        const options = picker.querySelector('.payment-method-options');
        if (!options) return;
        options.hidden = true;
        options.classList.remove('is-fixed', 'is-open-menu');
        options.style.position = '';
        options.style.left = '';
        options.style.right = '';
        options.style.top = '';
        options.style.bottom = '';
        options.style.width = '';
        options.style.maxHeight = '';
        options.style.zIndex = '';
        options.style.display = '';
        if (options.parentElement !== picker) picker.append(options);
      });
      methodPicker.classList.add('is-open');
      methodTrigger.setAttribute('aria-expanded', 'true');
      placeFixedMenu();
      if (focusSelected) {
        optionButtons.find((option) => option.dataset.method === select.value)?.focus();
      }
    };
    const updateMethod = () => {
      const isBkash = select.value === 'bkash';
      row.classList.toggle('payment-row-bkash', isBkash);
      const methodLabel = isBkash ? 'bKash' : 'By hand (cash)';
      methodTrigger.setAttribute('aria-label', `Payment method: ${methodLabel}`);
      methodTrigger.querySelector('.payment-method-label').textContent = methodLabel;
      document.getElementById('paymentMethodInput').value = select.value;
      row.querySelector('.payment-method-icon').innerHTML = isBkash
        ? `<img src="${esc(checkoutForm.dataset.bkashIcon)}" alt="">`
        : `<svg class="icon" aria-hidden="true" focusable="false"><use href="${esc(checkoutForm.dataset.icons)}#cash"></use></svg>`;
      optionButtons.forEach((option) => {
        const selected = option.dataset.method === select.value;
        option.setAttribute('aria-selected', String(selected));
        option.classList.toggle('is-selected', selected);
      });
      const details = row.querySelector('.bkash-payment-details');
      details.hidden = !isBkash;
      if (isBkash) {
        details.scrollIntoView({block: 'nearest', behavior: 'smooth'});
      }
    };
    select.addEventListener('change', updateMethod);
    methodTrigger.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (methodPicker.classList.contains('is-open')) closeMethodPicker();
      else openMethodPicker();
    });
    methodTrigger.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        openMethodPicker(true);
      }
    });
    optionButtons.forEach((option, index) => {
      option.addEventListener('click', () => {
        select.value = option.dataset.method;
        select.dispatchEvent(new Event('change', {bubbles:true}));
        closeMethodPicker(true);
      });
      option.addEventListener('keydown', (event) => {
        let nextIndex;
        if (event.key === 'ArrowDown') nextIndex = (index + 1) % optionButtons.length;
        else if (event.key === 'ArrowUp') nextIndex = (index - 1 + optionButtons.length) % optionButtons.length;
        else if (event.key === 'Home') nextIndex = 0;
        else if (event.key === 'End') nextIndex = optionButtons.length - 1;
        else if (event.key === 'Escape') {
          event.preventDefault();
          closeMethodPicker(true);
          return;
        } else if (event.key === 'Tab') {
          closeMethodPicker();
          return;
        } else return;
        event.preventDefault();
        optionButtons[nextIndex].focus();
      });
    });
    updateMethod();
    paymentRows.append(row);
    return row;
  };
  addPaymentRow('hand');

  paymentRows.addEventListener('click', (event) => {
    const zoomButton = event.target.closest('.bkash-qr-zoom');
    if (!zoomButton || bkashQrDialog.open) return;
    const qr = zoomButton.querySelector('.bkash-qr');
    const expandedQr = bkashQrDialog.querySelector('.bkash-qr-expanded');
    expandedQr.src = qr.currentSrc || qr.src;
    bkashQrDialog.showModal();
  });
  const findPaymentOptions = (picker) => {
    const optionsId = picker.querySelector('.payment-method-trigger')?.getAttribute('aria-controls');
    return (optionsId && document.getElementById(optionsId)) || picker.querySelector('.payment-method-options');
  };
  const resetPaymentOptions = (picker, options) => {
    picker.classList.remove('is-open');
    picker.querySelector('.payment-method-trigger')?.setAttribute('aria-expanded', 'false');
    if (!options) return;
    options.hidden = true;
    options.classList.remove('is-fixed', 'is-open-menu');
    options.style.position = '';
    options.style.left = '';
    options.style.right = '';
    options.style.top = '';
    options.style.bottom = '';
    options.style.width = '';
    options.style.maxHeight = '';
    options.style.zIndex = '';
    options.style.display = '';
    if (options.parentElement !== picker) picker.append(options);
  };
  document.addEventListener('pointerdown', (event) => {
    if (!(event.target instanceof Element)) return;
    document.querySelectorAll('.payment-method-picker.is-open').forEach((picker) => {
      const options = findPaymentOptions(picker);
      if (picker.contains(event.target) || options?.contains(event.target)) return;
      resetPaymentOptions(picker, options);
    });
  }, true);
  window.addEventListener('resize', () => {
    document.querySelectorAll('.payment-method-picker.is-open').forEach((picker) => {
      resetPaymentOptions(picker, findPaymentOptions(picker));
    });
  });
  bkashQrDialog.querySelector('.bkash-qr-dialog-close').addEventListener('click', () => {
    bkashQrDialog.close();
  });
  bkashQrDialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    bkashQrDialog.close();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && bkashQrDialog.open) bkashQrDialog.close();
  });
  bkashQrDialog.addEventListener('click', (event) => {
    if (event.target === bkashQrDialog) bkashQrDialog.close();
  });
  bkashQrDialog.addEventListener('close', () => {
    bkashQrDialog.querySelector('.bkash-qr-expanded').removeAttribute('src');
  });

  function totals() {
    let subtotal = 0;
    cart.forEach((item) => { subtotal += item.price * item.quantity; });
    const discountElement = document.getElementById('discountInput');
    const discountValue = Math.max(0, Number(discountElement ? discountElement.value : 0) || 0);
    const discountKind = document.getElementById('discountKind')?.value || 'amount';
    const discount = Math.min(subtotal, discountKind === 'percent' ? subtotal * Math.min(discountValue, 100) / 100 : discountValue);
    const couponBeforeCap = appliedCoupon
      ? (appliedCoupon.discount_type === 'percent'
        ? Math.round(subtotal * Math.min(Number(appliedCoupon.discount_value), 100)) / 100
        : Number(appliedCoupon.discount_value))
      : 0;
    const couponDiscount = Math.min(Math.max(0, subtotal - discount), couponBeforeCap);
    const total = Math.max(0, Math.round((subtotal - discount - couponDiscount) * 100) / 100);
    return {subtotal, total, couponDiscount};
  }
  function renderTotals() {
    const {subtotal, total, couponDiscount} = totals();
    document.getElementById('subtotalText').textContent = currency(subtotal);
    document.getElementById('totalText').textContent = currency(total);
    const couponLine = document.getElementById('couponTotalLine');
    couponLine.hidden = !appliedCoupon;
    if (appliedCoupon) {
      document.getElementById('couponTotalCode').textContent = `(${appliedCoupon.code})`;
      document.getElementById('couponTotalText').textContent = `−${currency(couponDiscount)}`;
      couponStatus.textContent = `${appliedCoupon.code} applied. Coupon savings: ${currency(couponDiscount)}.`;
      couponCodeInput.value = appliedCoupon.code;
      document.getElementById('resetCoupon').hidden = false;
      document.getElementById('applyCoupon').hidden = true;
      couponInput.disabled = true;
    } else {
      couponCodeInput.value = '';
      document.getElementById('resetCoupon').hidden = true;
      document.getElementById('applyCoupon').hidden = false;
      couponInput.disabled = false;
    }
    document.getElementById('checkoutButton').disabled = cart.size === 0;
    document.getElementById('cartCount').textContent = [...cart.values()].reduce((n, item) => n + item.quantity, 0);
  }
  function renderCart() {
    if (!cart.size) {
      cartItems.innerHTML = `<div class="cart-empty"><span class="empty-icon"><svg class="icon" aria-hidden="true" focusable="false"><use href="${esc(cartItems.dataset.cartIcon)}"></use></svg></span><p>Your order starts here.<br>Pick something delicious!</p></div>`;
      renderTotals();
      return;
    }
    cartItems.innerHTML = [...cart.values()].map((item) => {
      const addonText = item.addons.length ? `<small class="cart-addons">Extras: ${item.addons.map((addon) => esc(addon.name)).join(', ')}</small>` : '';
      return `<div class="cart-line"><div class="cart-line-info"><b>${esc(item.name)}</b>${addonText}<small>${currency(item.price)} each</small></div><div class="qty-control"><button type="button" data-qty="-1" data-id="${esc(item.key)}" aria-label="Decrease quantity">−</button><span>${item.quantity}</span><button type="button" data-qty="1" data-id="${esc(item.key)}" aria-label="Increase quantity">＋</button></div><b class="cart-line-total">${currency(item.price * item.quantity)}</b><button class="remove-cart" type="button" data-remove="${esc(item.key)}" aria-label="Remove item">×</button></div>`;
    }).join('');
    cartItems.querySelectorAll('[data-qty]').forEach((button) => button.addEventListener('click', () => {
      const item = cart.get(button.dataset.id);
      const productButton = document.querySelector(`.pos-product[data-product-id="${item.productId}"]`);
      const quantityInCart = [...cart.values()].filter((line) => line.productId === item.productId).reduce((sum, line) => sum + line.quantity, 0);
      if (Number(button.dataset.qty) > 0 && quantityInCart >= Number(productButton.dataset.stock)) {
        document.getElementById('posNotice').textContent = `Only ${productButton.dataset.stock} ${item.name} in stock.`;
        return;
      }
      item.quantity += Number(button.dataset.qty);
      if (item.quantity <= 0) cart.delete(button.dataset.id);
      renderCart();
    }));
    cartItems.querySelectorAll('[data-remove]').forEach((button) => button.addEventListener('click', () => { cart.delete(button.dataset.remove); renderCart(); }));
    renderTotals();
  }
  function ingredientUsage() {
    const usage = new Map();
    cart.forEach((item) => item.addons.forEach((addon) => {
      usage.set(addon.id, (usage.get(addon.id) || 0) + Number(addon.amount) * item.quantity);
    }));
    return usage;
  }
  function addProduct(product, addons) {
    const quantityInCart = [...cart.values()].filter((item) => item.productId === product.id).reduce((sum, item) => sum + item.quantity, 0);
    if (quantityInCart >= product.stock) {
      document.getElementById('posNotice').textContent = `Only ${product.stock} ${product.name} in stock.`;
      return;
    }
    const addonIds = addons.map((addon) => addon.id).sort((a, b) => a - b);
    const key = `${product.id}:${addonIds.join(',')}`;
    const price = product.price + addons.reduce((sum, addon) => sum + Number(addon.price), 0);
    const existing = cart.get(key);
    if (existing) existing.quantity += 1;
    else cart.set(key, {key, productId:product.id, name:product.name, price, quantity:1, addons});
    document.getElementById('posNotice').textContent = '';
    renderCart();
  }
  function selectedDialogAddons() {
    const selectedIds = new Set([...addonChoices.querySelectorAll('input:checked')].map((input) => Number(input.value)));
    return pendingProduct.addons.filter((addon) => selectedIds.has(addon.id));
  }
  function updateAddonDialog() {
    const usage = ingredientUsage();
    const selected = selectedDialogAddons();
    let enoughStock = true;
    let unavailable = false;
    addonChoices.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      const addon = pendingProduct.addons.find((item) => item.id === Number(input.value));
      const available = Number(addon.stock) - (usage.get(addon.id) || 0);
      const canAdd = available >= Number(addon.amount);
      input.disabled = !canAdd && !input.checked;
      input.closest('.addon-choice').classList.toggle('unavailable', !canAdd);
      unavailable = unavailable || !canAdd;
      if (input.checked && !canAdd) enoughStock = false;
    });
    addonMessage.textContent = !enoughStock
      ? 'There is not enough ingredient stock for this selection.'
      : unavailable
        ? 'Some extras are unavailable because ingredient stock is low.'
        : '';
    confirmAddons.disabled = !enoughStock;
    confirmAddons.textContent = `Add · ${currency(pendingProduct.price + selected.reduce((sum, addon) => sum + Number(addon.price), 0))}`;
  }
  function openAddonDialog(product) {
    pendingProduct = product;
    document.getElementById('addonDialogTitle').textContent = `Extras for ${product.name}`;
    addonChoices.innerHTML = product.addons.map((addon) => `<label class="addon-choice"><input type="checkbox" value="${addon.id}"><span><b>${esc(addon.name)}</b><small>Uses ${esc(addon.amount)} ${esc(addon.unit)} · ${currency(addon.price)} · ${esc(addon.stock)} ${esc(addon.unit)} in stock</small></span></label>`).join('');
    addonChoices.querySelectorAll('input').forEach((input) => input.addEventListener('change', updateAddonDialog));
    updateAddonDialog();
    addonDialog.showModal();
  }
  document.querySelectorAll('.pos-product').forEach((button) => button.addEventListener('click', () => {
    const product = {
      id:Number(button.dataset.productId),
      name:button.dataset.name,
      price:Number(button.dataset.price),
      stock:Number(button.dataset.stock),
      addons:JSON.parse(button.dataset.addons || '[]')
    };
    if (product.addons.length) openAddonDialog(product);
    else addProduct(product, []);
  }));
  confirmAddons.addEventListener('click', () => {
    if (pendingProduct) addProduct(pendingProduct, selectedDialogAddons());
    addonDialog.close();
  });
  document.getElementById('cancelAddons').addEventListener('click', () => addonDialog.close());
  document.getElementById('clearCart').addEventListener('click', () => { cart.clear(); renderCart(); });
  document.getElementById('discountInput')?.addEventListener('input', renderTotals);
  document.getElementById('discountKind')?.addEventListener('change', renderTotals);
  async function applyCoupon() {
    if (checkingCoupon) return;
    const code = couponInput.value.trim().toUpperCase();
    if (!code) {
      couponStatus.textContent = 'Enter a coupon code first.';
      return;
    }
    const {subtotal} = totals();
    if (subtotal <= 0) {
      couponStatus.textContent = 'Add items to the order before applying a coupon.';
      return;
    }
    const button = document.getElementById('applyCoupon');
    checkingCoupon = true;
    button.disabled = true;
    couponStatus.textContent = 'Checking coupon…';
    const body = new URLSearchParams({
      csrf_token: checkoutForm.querySelector('[name="csrf_token"]').value,
      code,
      subtotal: subtotal.toFixed(2)
    });
    try {
      const response = await fetch(checkoutForm.dataset.couponUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
        body
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not validate this coupon.');
      appliedCoupon = result;
      renderTotals();
    } catch (error) {
      couponStatus.textContent = error instanceof Error ? error.message : 'Could not validate this coupon.';
    } finally {
      checkingCoupon = false;
      button.disabled = false;
    }
  }
  document.getElementById('applyCoupon').addEventListener('click', applyCoupon);
  couponInput.addEventListener('change', () => {
    if (couponInput.value.trim()) applyCoupon();
  });
  couponInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      applyCoupon();
    }
  });
  document.getElementById('resetCoupon').addEventListener('click', () => {
    appliedCoupon = null;
    couponInput.value = '';
    couponStatus.textContent = 'Coupon removed.';
    renderTotals();
    couponInput.focus();
  });
  let activeCategory = '';
  const filterProducts = () => {
    const q = document.getElementById('productSearch').value.trim().toLowerCase();
    document.querySelectorAll('.pos-product').forEach((product) => {
      product.hidden = (activeCategory && product.dataset.category !== activeCategory) || (q && !product.dataset.name.toLowerCase().includes(q));
    });
  };
  document.getElementById('productSearch').addEventListener('input', filterProducts);
  document.querySelectorAll('.chip').forEach((chip) => chip.addEventListener('click', () => {
    activeCategory = chip.dataset.category; document.querySelectorAll('.chip').forEach((c) => c.classList.toggle('active', c === chip)); filterProducts();
  }));
  checkoutForm.addEventListener('submit', (event) => {
    if (!cart.size) { event.preventDefault(); return; }
    document.getElementById('cartJson').value = JSON.stringify([...cart.values()].map((item) => ({
      id:item.productId,
      quantity:item.quantity,
      addons:item.addons.map((addon) => addon.id)
    })));
    document.getElementById('paymentMethodInput').value = paymentRows.querySelector('.payment-method-value').value;
    document.getElementById('checkoutButton').disabled = true;
    document.getElementById('checkoutButton').textContent = 'Saving order…';
  });
  renderCart();
})();

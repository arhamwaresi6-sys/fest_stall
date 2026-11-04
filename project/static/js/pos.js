(() => {
  const cart = new Map();
  const cartItems = document.getElementById('cartItems');
  if (!cartItems) return;
  const paymentRows = document.getElementById('paymentRows');
  const currency = (number) => (document.body.dataset.currency || '৳').replace(/[&<>"']/g, '') + Number(number || 0).toLocaleString('en-BD', {minimumFractionDigits:2, maximumFractionDigits:2});
  const esc = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const addPaymentRow = (method = 'hand', amount = '', automatic = false) => {
    const row = document.createElement('div');
    row.className = 'payment-input-row';
    row.dataset.automatic = automatic ? '1' : '0';
    row.innerHTML = `<select aria-label="Payment method"><option value="hand">By hand (cash)</option><option value="bkash">bKash</option></select><input class="payment-amount" type="number" min="0" step="0.01" placeholder="Amount" aria-label="Payment amount"><input class="payment-reference" maxlength="120" placeholder="Ref. ID (optional)" aria-label="Reference ID"><button class="remove-payment" type="button" aria-label="Remove payment">×</button>`;
    const select = row.querySelector('select');
    const input = row.querySelector('.payment-amount');
    select.value = method;
    input.value = amount;
    input.addEventListener('input', () => { row.dataset.automatic = '0'; renderTotals(); });
    row.querySelector('.remove-payment').addEventListener('click', () => { row.remove(); renderTotals(); });
    paymentRows.append(row);
    return row;
  };
  addPaymentRow('hand', '0.00', true);

  function totals() {
    let subtotal = 0;
    cart.forEach((item) => { subtotal += item.price * item.quantity; });
    const discountElement = document.getElementById('discountInput');
    const discountValue = Math.max(0, Number(discountElement ? discountElement.value : 0) || 0);
    const discountKind = document.getElementById('discountKind')?.value || 'amount';
    const discount = discountKind === 'percent' ? subtotal * Math.min(discountValue, 100) / 100 : discountValue;
    return {subtotal, total: Math.max(0, Math.round((subtotal - discount) * 100) / 100)};
  }
  function renderTotals() {
    const {subtotal, total} = totals();
    document.getElementById('subtotalText').textContent = currency(subtotal);
    document.getElementById('totalText').textContent = currency(total);
    const rows = [...paymentRows.querySelectorAll('.payment-input-row')];
    const firstAuto = rows.find((row) => row.dataset.automatic === '1');
    if (firstAuto) firstAuto.querySelector('.payment-amount').value = total.toFixed(2);
    const paid = rows.reduce((sum, row) => sum + Math.max(0, Number(row.querySelector('.payment-amount').value) || 0), 0);
    const balance = Math.max(0, total - paid);
    const balanceEl = document.getElementById('paymentBalance');
    balanceEl.textContent = paid > total ? `Over by · ${currency(paid-total)}` : (balance > 0 ? `Remaining · ${currency(balance)}` : `Fully paid · ${currency(paid)}`);
    balanceEl.classList.toggle('danger-text', paid > total);
    document.getElementById('checkoutButton').disabled = cart.size === 0 || paid > total;
    document.getElementById('cartCount').textContent = [...cart.values()].reduce((n, item) => n + item.quantity, 0);
  }
  function renderCart() {
    if (!cart.size) {
      cartItems.innerHTML = '<div class="cart-empty"><span>🛒</span><p>Your order starts here.<br>Pick something delicious!</p></div>';
      renderTotals();
      return;
    }
    cartItems.innerHTML = [...cart.values()].map((item) => `<div class="cart-line"><div class="cart-line-info"><b>${esc(item.name)}</b><small>${currency(item.price)} each</small></div><div class="qty-control"><button type="button" data-qty="-1" data-id="${item.id}" aria-label="Decrease quantity">−</button><span>${item.quantity}</span><button type="button" data-qty="1" data-id="${item.id}" aria-label="Increase quantity">＋</button></div><b class="cart-line-total">${currency(item.price * item.quantity)}</b><button class="remove-cart" type="button" data-remove="${item.id}" aria-label="Remove item">×</button></div>`).join('');
    cartItems.querySelectorAll('[data-qty]').forEach((button) => button.addEventListener('click', () => {
      const item = cart.get(button.dataset.id); item.quantity += Number(button.dataset.qty);
      if (item.quantity <= 0) cart.delete(button.dataset.id);
      renderCart();
    }));
    cartItems.querySelectorAll('[data-remove]').forEach((button) => button.addEventListener('click', () => { cart.delete(button.dataset.remove); renderCart(); }));
    renderTotals();
  }
  document.querySelectorAll('.pos-product').forEach((button) => button.addEventListener('click', () => {
    const id = button.dataset.productId;
    const item = cart.get(id) || {id, name:button.dataset.name, price:Number(button.dataset.price), quantity:0};
    item.quantity += 1; cart.set(id, item); renderCart();
  }));
  document.getElementById('clearCart').addEventListener('click', () => { cart.clear(); renderCart(); });
  document.getElementById('discountInput')?.addEventListener('input', renderTotals);
  document.getElementById('discountKind')?.addEventListener('change', renderTotals);
  document.getElementById('addPayment').addEventListener('click', () => {
    const first = paymentRows.querySelector('.payment-input-row');
    if (first && first.dataset.automatic === '1') { first.dataset.automatic = '0'; first.querySelector('.payment-amount').value = ''; }
    addPaymentRow('bkash', '', false);
    renderTotals();
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
  document.getElementById('checkoutForm').addEventListener('submit', (event) => {
    const {total} = totals();
    const payments = [...paymentRows.querySelectorAll('.payment-input-row')].map((row) => ({
      method: row.querySelector('select').value,
      amount: Number(row.querySelector('.payment-amount').value) || 0,
      reference: row.querySelector('.payment-reference').value.trim()
    })).filter((row) => row.amount > 0);
    const paymentTotal = payments.reduce((sum, row) => sum + row.amount, 0);
    if (!cart.size || paymentTotal > total + 0.001) { event.preventDefault(); return; }
    document.getElementById('cartJson').value = JSON.stringify([...cart.values()].map(({id, quantity}) => ({id:Number(id), quantity})));
    document.getElementById('paymentsJson').value = JSON.stringify(payments);
    document.getElementById('checkoutButton').disabled = true;
    document.getElementById('checkoutButton').textContent = 'Saving order…';
  });
  renderCart();
})();

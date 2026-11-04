(() => {
  const rows = document.getElementById('addonRows');
  const template = document.getElementById('addonRowTemplate');
  const addButton = document.getElementById('addAddon');
  if (!rows || !template || !addButton) return;
  addButton.addEventListener('click', () => rows.append(template.content.cloneNode(true)));
  rows.addEventListener('click', (event) => {
    const button = event.target.closest('.remove-addon');
    if (button) button.closest('.addon-config-row').remove();
  });
})();

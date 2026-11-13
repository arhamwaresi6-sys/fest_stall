document.addEventListener('DOMContentLoaded', () => {
  const clearFixedMenu = (menu, host) => {
    menu.hidden = true;
    menu.classList.remove('is-fixed', 'is-open-menu');
    menu.style.position = '';
    menu.style.left = '';
    menu.style.right = '';
    menu.style.top = '';
    menu.style.bottom = '';
    menu.style.width = '';
    menu.style.minWidth = '';
    menu.style.maxHeight = '';
    menu.style.zIndex = '';
    menu.style.display = '';
    if (host && menu.parentElement !== host) host.append(menu);
  };
  const placeFixedMenu = (anchor, menu, wrapper) => {
    if (menu.parentElement !== document.body) document.body.append(menu);
    menu.hidden = false;
    menu.classList.add('is-fixed', 'is-open-menu');
    menu.style.display = 'grid';
    const rect = anchor.getBoundingClientRect();
    const viewportPadding = 12;
    const gap = 6;
    const menuHeight = Math.min(menu.scrollHeight || 180, 320);
    const spaceAbove = Math.max(0, rect.top - viewportPadding - gap);
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - viewportPadding - gap);
    const opensUp = spaceBelow < menuHeight && spaceAbove > spaceBelow;
    const availableHeight = opensUp ? spaceAbove : spaceBelow;
    const maxHeight = Math.min(menuHeight, availableHeight);
    const maxWidth = Math.max(0, window.innerWidth - viewportPadding * 2);
    const width = Math.min(Math.max(rect.width, 72), maxWidth);
    const left = Math.max(viewportPadding, Math.min(rect.left, window.innerWidth - width - viewportPadding));
    wrapper?.classList.toggle('opens-up', opensUp);
    menu.style.position = 'fixed';
    menu.style.left = `${left}px`;
    menu.style.width = `${width}px`;
    menu.style.right = 'auto';
    menu.style.maxHeight = `${maxHeight}px`;
    menu.style.zIndex = '80';
    if (opensUp) {
      menu.style.top = 'auto';
      menu.style.bottom = `${window.innerHeight - rect.top + gap}px`;
    } else {
      menu.style.top = `${rect.bottom + gap}px`;
      menu.style.bottom = 'auto';
    }
  };

  let autocompleteCount = 0;
  const openAutocompletes = new Set();
  document.querySelectorAll('input[list]').forEach((input) => {
    const datalist = document.getElementById(input.getAttribute('list'));
    if (!datalist) return;
    autocompleteCount += 1;
    const wrapper = document.createElement('div');
    wrapper.className = 'input-suggestions';
    const menu = document.createElement('div');
    menu.className = 'input-suggestions-menu';
    menu.id = `input-suggestions-${autocompleteCount}`;
    menu.hidden = true;
    menu.setAttribute('role', 'listbox');
    menu.setAttribute('aria-label', `${input.name.replace(/[_-]+/g, ' ')} suggestions`);
    input.removeAttribute('list');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', menu.id);
    datalist.hidden = true;
    input.parentNode.insertBefore(wrapper, input);
    wrapper.append(input, menu);
    const state = {wrapper, input, menu, close: null};
    const options = [...datalist.options].map((option) => option.value || option.label).filter(Boolean);
    const close = (restoreFocus = false) => {
      input.setAttribute('aria-expanded', 'false');
      wrapper.classList.remove('is-open', 'opens-up');
      clearFixedMenu(menu, wrapper);
      openAutocompletes.delete(state);
      if (restoreFocus) input.focus();
    };
    const render = (focusOption = false) => {
      const query = input.value.trim().toLocaleLowerCase();
      const matchingOptions = options.filter((option) => option.toLocaleLowerCase().includes(query));
      menu.replaceChildren();
      matchingOptions.forEach((value, index) => {
        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'input-suggestion-option';
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', String(value === input.value));
        option.textContent = value;
        option.id = `${menu.id}-option-${index}`;
        option.addEventListener('pointerdown', (event) => event.preventDefault());
        option.addEventListener('click', () => {
          input.value = value;
          input.dispatchEvent(new Event('input', {bubbles: true}));
          input.dispatchEvent(new Event('change', {bubbles: true}));
          close(true);
        });
        option.addEventListener('keydown', (event) => {
          const buttons = [...menu.querySelectorAll('.input-suggestion-option')];
          const index = buttons.indexOf(option);
          let nextIndex;
          if (event.key === 'ArrowDown') nextIndex = (index + 1) % buttons.length;
          else if (event.key === 'ArrowUp') nextIndex = (index - 1 + buttons.length) % buttons.length;
          else if (event.key === 'Home') nextIndex = 0;
          else if (event.key === 'End') nextIndex = buttons.length - 1;
          else if (event.key === 'Escape') {
            event.preventDefault();
            close(true);
            return;
          } else if (event.key === 'Tab') {
            close();
            return;
          } else return;
          event.preventDefault();
          buttons[nextIndex]?.focus();
        });
        menu.append(option);
      });
      if (!matchingOptions.length) {
        close();
        return;
      }
      input.setAttribute('aria-expanded', 'true');
      wrapper.classList.add('is-open');
      openAutocompletes.add(state);
      placeFixedMenu(input, menu, wrapper);
      if (focusOption) menu.querySelector('.input-suggestion-option')?.focus();
    };
    state.close = close;
    input.addEventListener('focus', () => render());
    input.addEventListener('input', () => render());
    input.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        render(true);
        if (event.key === 'ArrowUp') {
          const buttons = menu.querySelectorAll('.input-suggestion-option');
          buttons[buttons.length - 1]?.focus();
        }
      } else if (event.key === 'Escape' && !menu.hidden) {
        event.preventDefault();
        close();
      } else if (event.key === 'Tab') close();
    });
  });
  document.addEventListener('pointerdown', (event) => {
    openAutocompletes.forEach((state) => {
      if (state.wrapper.contains(event.target) || state.menu.contains(event.target)) return;
      state.close();
    });
  }, true);

  let customSelectCount = 0;
  const customSelects = new WeakMap();
  const openCustomSelects = new Set();
  const readLabel = (select) => {
    const label = select.closest('label');
    const text = label
      ? [...label.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent.trim()).filter(Boolean).join(' ')
      : '';
    return select.getAttribute('aria-label') || text || select.name.replace(/[_-]+/g, ' ');
  };
  const enhanceSelect = (select) => {
    if (customSelects.has(select) || select.multiple || select.size > 1 || select.classList.contains('payment-method-value')) return;
    customSelectCount += 1;
    const wrapper = document.createElement('div');
    wrapper.className = 'custom-select';
    const trigger = document.createElement('button');
    trigger.className = 'custom-select-trigger';
    trigger.type = 'button';
    trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-label', readLabel(select));
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    const menu = document.createElement('div');
    menu.className = 'custom-select-menu';
    menu.id = `custom-select-menu-${customSelectCount}`;
    menu.hidden = true;
    menu.setAttribute('role', 'listbox');
    menu.setAttribute('aria-label', `${readLabel(select)} options`);
    trigger.setAttribute('aria-controls', menu.id);
    const required = select.required;
    const error = document.createElement('span');
    error.className = 'custom-select-error';
    error.id = `${menu.id}-error`;
    error.setAttribute('role', 'alert');
    error.hidden = true;
    select.required = false;
    select.classList.add('custom-select-native');
    select.setAttribute('aria-hidden', 'true');
    select.tabIndex = -1;
    select.parentNode.insertBefore(wrapper, select);
    wrapper.append(select, trigger, menu, error);
    if (required) trigger.setAttribute('aria-required', 'true');

    const state = {wrapper, trigger, menu, error, select, required, render: null, close: null, open: null};
    customSelects.set(select, state);
    const clearError = () => {
      error.hidden = true;
      trigger.removeAttribute('aria-invalid');
    };
    const updateSelected = () => {
      const selected = select.selectedOptions[0];
      trigger.textContent = selected ? selected.textContent.trim() : 'Choose an option';
      menu.querySelectorAll('[role="option"]').forEach((optionButton) => {
        const isSelected = optionButton.dataset.value === select.value;
        optionButton.setAttribute('aria-selected', String(isSelected));
        optionButton.classList.toggle('is-selected', isSelected);
      });
    };
    const close = (restoreFocus = false) => {
      wrapper.classList.remove('is-open', 'opens-up');
      trigger.setAttribute('aria-expanded', 'false');
      clearFixedMenu(menu, wrapper);
      openCustomSelects.delete(state);
      if (restoreFocus) trigger.focus();
    };
    const enabledOptions = () => [...menu.querySelectorAll('[role="option"]:not(:disabled)')];
    const open = (focusSelected = false) => {
      openCustomSelects.forEach((otherState) => {
        if (otherState !== state) otherState.close();
      });
      wrapper.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
      openCustomSelects.add(state);
      placeFixedMenu(trigger, menu, wrapper);
      if (focusSelected) {
        const selected = enabledOptions().find((option) => option.dataset.value === select.value);
        (selected || enabledOptions()[0])?.focus();
      }
    };
    const render = () => {
      menu.replaceChildren();
      [...select.options].forEach((option, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'custom-select-option';
        button.setAttribute('role', 'option');
        button.dataset.value = option.value;
        button.textContent = option.textContent.trim();
        button.disabled = option.disabled;
        button.setAttribute('aria-selected', String(option.selected));
        button.id = `${menu.id}-option-${index}`;
        button.addEventListener('pointerdown', (event) => event.stopPropagation());
        button.addEventListener('click', () => {
          select.value = option.value;
          select.dispatchEvent(new Event('change', {bubbles: true}));
          clearError();
          close(true);
        });
        button.addEventListener('keydown', (event) => {
          const options = enabledOptions();
          const index = options.indexOf(button);
          let nextIndex;
          if (event.key === 'ArrowDown') nextIndex = (index + 1) % options.length;
          else if (event.key === 'ArrowUp') nextIndex = (index - 1 + options.length) % options.length;
          else if (event.key === 'Home') nextIndex = 0;
          else if (event.key === 'End') nextIndex = options.length - 1;
          else if (event.key === 'Escape') {
            event.preventDefault();
            close(true);
            return;
          } else if (event.key === 'Tab') {
            close();
            return;
          } else return;
          event.preventDefault();
          options[nextIndex]?.focus();
        });
        menu.append(button);
      });
      updateSelected();
    };
    state.render = render;
    state.close = close;
    state.open = open;
    render();
    trigger.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (wrapper.classList.contains('is-open')) close();
      else open();
    });
    trigger.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        open(true);
      } else if (event.key === 'Escape' && wrapper.classList.contains('is-open')) {
        event.preventDefault();
        close(true);
      }
    });
    select.addEventListener('change', () => {
      updateSelected();
      clearError();
    });
    if (select.form) {
      select.form.addEventListener('submit', (event) => {
        if (!required || select.disabled || select.value) return;
        event.preventDefault();
        error.textContent = 'Please choose an option.';
        error.hidden = false;
        trigger.setAttribute('aria-invalid', 'true');
        trigger.setAttribute('aria-describedby', error.id);
        trigger.focus();
        open();
      });
      select.form.addEventListener('reset', () => window.setTimeout(() => {
        updateSelected();
        clearError();
      }));
    }
  };
  document.querySelectorAll('select').forEach(enhanceSelect);
  const selectObserver = new MutationObserver((records) => {
    records.forEach((record) => {
      if (record.target instanceof HTMLSelectElement) {
        customSelects.get(record.target)?.render();
      }
      record.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        if (node.matches('select')) enhanceSelect(node);
        node.querySelectorAll('select').forEach(enhanceSelect);
      });
    });
  });
  selectObserver.observe(document.body, {childList: true, subtree: true});
  document.addEventListener('pointerdown', (event) => {
    openCustomSelects.forEach((state) => {
      if (state.wrapper.contains(event.target) || state.menu.contains(event.target)) return;
      state.close();
    });
  }, true);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') openCustomSelects.forEach((state) => state.close(true));
  });
  window.addEventListener('resize', () => {
    openCustomSelects.forEach((state) => state.close());
    openAutocompletes.forEach((state) => state.close());
  });
  document.addEventListener('scroll', (event) => {
    const target = event.target;
    openCustomSelects.forEach((state) => {
      if (target === state.menu || state.menu.contains(target)) return;
      state.close();
    });
    openAutocompletes.forEach((state) => {
      if (target === state.menu || state.menu.contains(target)) return;
      state.close();
    });
  }, true);

  const sidebar = document.getElementById('sidebar');
  const menuToggle = document.getElementById('menuToggle');
  const backdrop = document.getElementById('sidebarBackdrop');
  const setMenuOpen = (open) => {
    if (!sidebar || !menuToggle || !backdrop) return;
    sidebar.classList.toggle('open', open);
    backdrop.classList.toggle('open', open);
    menuToggle.setAttribute('aria-expanded', String(open));
    menuToggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  };
  menuToggle?.addEventListener('click', () => {
    setMenuOpen(!sidebar.classList.contains('open'));
  });
  backdrop?.addEventListener('click', () => setMenuOpen(false));
  sidebar?.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', () => setMenuOpen(false));
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setMenuOpen(false);
  });
  window.addEventListener('resize', () => {
    if (window.innerWidth > 900) setMenuOpen(false);
  });

  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
});

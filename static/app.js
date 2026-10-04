document.addEventListener("DOMContentLoaded", () => {
  const signupError = document.querySelector("[data-signup-error]");
  if (signupError) {
    const closeButton = signupError.querySelector("[data-signup-error-close]");
    const dismissError = () => signupError.remove();
    closeButton?.addEventListener("click", dismissError);
    signupError.addEventListener("click", (event) => {
      if (event.target === signupError) dismissError();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") dismissError();
    }, { once: true });
    closeButton?.focus();
  }

  document.querySelectorAll("[data-cancel-order]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (!window.confirm("Cancel this order? You can only cancel before payment.")) {
        event.preventDefault();
      }
    });
  });

  const orderPopup = document.querySelector("[data-order-popup]");
  if (orderPopup) {
    const closeButtons = orderPopup.querySelectorAll("[data-popup-close]");
    const dismissPopup = () => orderPopup.remove();
    closeButtons.forEach((button) => button.addEventListener("click", dismissPopup));
    orderPopup.addEventListener("click", (event) => {
      if (event.target === orderPopup) dismissPopup();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") dismissPopup();
    }, { once: true });
    closeButtons[0]?.focus();
  }

  const fileInput = document.querySelector("#document");
  const fileLabel = document.querySelector("[data-file-name]");

  if (fileInput && fileLabel) {
    fileInput.addEventListener("change", () => {
      fileLabel.textContent = fileInput.files[0]?.name || "Choose a document";
      fileInput.closest(".upload-zone")?.classList.toggle("has-file", Boolean(fileInput.files.length));
    });
  }

  const orderForm = document.querySelector("[data-order-form]");
  if (orderForm) {
    const priceData = JSON.parse(document.querySelector("#digital-price-data")?.textContent || "{}");
    const categoryInputs = orderForm.querySelectorAll("[name='product_category']");
    const deliveryInputs = orderForm.querySelectorAll("[name='delivery_type']");
    const digitalFields = orderForm.querySelectorAll("[data-digital-field]");
    const cadField = orderForm.querySelector("[data-cad-field]");
    const cadSize = orderForm.querySelector("#cad_size");
    const deliveryAddressField = orderForm.querySelector("[data-delivery-address]");
    const deliveryAddress = orderForm.querySelector("#delivery_address");
    const notes = orderForm.querySelector("[data-order-notes]");
    const notesLabel = orderForm.querySelector("[data-notes-label]");
    const notesOptional = notesLabel.querySelector(".optional");
    const notesHint = orderForm.querySelector("[data-notes-hint]");
    const pricePreview = orderForm.querySelector("[data-price-preview]");
    const priceTotal = orderForm.querySelector("[data-price-total]");
    const priceUnit = orderForm.querySelector("[data-price-unit]");
    const priceHint = orderForm.querySelector("[data-price-hint]");
    const orderHelp = orderForm.querySelector("[data-order-help]");
    const orderLabel = orderForm.querySelector("[data-order-label]");
    const submitButton = orderForm.querySelector("[data-order-submit]");
    const quantity = orderForm.querySelector("[data-price-qty]");
    const sizeSelect = orderForm.querySelector("[data-price-size]");
    const modeSelect = orderForm.querySelector("[data-price-mode]");

    const updateOrderForm = () => {
      const category = orderForm.querySelector("[name='product_category']:checked")?.value;
      const isDigital = category === "digital_printing";
      const deliveryType = orderForm.querySelector("[name='delivery_type']:checked")?.value;
      const isDelivery = deliveryType === "delivery";
      const isCustomCad = !isDigital && cadSize.value === "Custom";
      digitalFields.forEach((field) => {
        field.hidden = !isDigital;
        field.querySelector("select").disabled = !isDigital;
      });
      cadField.hidden = isDigital;
      cadSize.disabled = isDigital;
      deliveryAddressField.hidden = !isDelivery;
      deliveryAddress.disabled = !isDelivery;
      deliveryAddress.required = isDelivery;
      notes.required = isCustomCad;
      notesHint.hidden = !isCustomCad;
      notesOptional.hidden = isCustomCad;
      notesLabel.firstChild.textContent = isCustomCad ? "Extra notes (required) " : "Anything we should know ";
      pricePreview.hidden = !isDigital;

      if (!isDigital) {
        orderHelp.textContent = isDelivery
          ? "CAD delivery charges will be included in the quotation."
          : "CAD orders are quoted by the print desk.";
        orderLabel.textContent = "Send CAD for a quote";
        submitButton.disabled = false;
        return;
      }

      orderHelp.textContent = "Your total is calculated from the configured rate per sheet.";
      orderLabel.textContent = "Continue to payment";
      const sheetRate = priceData[sizeSelect.value]?.[modeSelect.value];
      const sheetCount = Number(quantity.value);
      if (!sheetRate || !Number.isInteger(sheetCount) || sheetCount < 1) {
        priceTotal.textContent = "Rate not set";
        priceUnit.textContent = "";
        priceHint.textContent = "The print desk needs to configure this size and print mode.";
        submitButton.disabled = true;
        return;
      }

      const deliveryFee = isDelivery ? Number(priceData.delivery_fee_paise || 0) : 0;
      const total = sheetRate * sheetCount + deliveryFee;
      priceTotal.textContent = `₹${(total / 100).toFixed(2)}`;
      priceUnit.textContent = `₹${(sheetRate / 100).toFixed(2)} per sheet`;
      priceHint.textContent = `${sheetCount} sheet${sheetCount === 1 ? "" : "s"} × ₹${(sheetRate / 100).toFixed(2)}${deliveryFee ? ` + ₹${(deliveryFee / 100).toFixed(2)} delivery` : ""}`;
      submitButton.disabled = false;
    };

    categoryInputs.forEach((input) => input.addEventListener("change", updateOrderForm));
    deliveryInputs.forEach((input) => input.addEventListener("change", updateOrderForm));
    [quantity, sizeSelect, modeSelect].forEach((input) => input.addEventListener("input", updateOrderForm));
    [sizeSelect, modeSelect, cadSize].forEach((input) => input.addEventListener("change", updateOrderForm));
    updateOrderForm();
  }
});
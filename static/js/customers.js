const syncCustomerFields = (form) => {
  const company = form.querySelector("#id_customer_type")?.value === "company";
  const domestic = (form.querySelector("#id_country_code")?.value || "ES").toUpperCase() === "ES";
  form.querySelectorAll("[data-company-field]").forEach((field) => { field.hidden = !company; });
  form.querySelectorAll("[data-national-tax]").forEach((field) => { field.hidden = !domestic; });
  form.querySelectorAll("[data-foreign-tax]").forEach((field) => { field.hidden = domestic; });
};
document.querySelectorAll("[data-customer-form]").forEach((form) => {
  syncCustomerFields(form);
  form.addEventListener("change", () => syncCustomerFields(form));
});

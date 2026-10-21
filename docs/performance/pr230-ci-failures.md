# PR #230: inventario de fallos originales

Fuente: [ejecución 39603618984](https://github.com/daniilabradorr/sala-tpv/actions/runs/39603618984), job `browser-e2e` (119234083294), commit `1834c43`. Logs completos descargados; 131 tests, 40 errors y 11 failures.

No son 51 defectos independientes. A = assets con hash interceptados por el servidor estático del arnés; B = checkout antes de validar la lectura inicial; C = aserción agregada tras fallar un subtest por B.

| # | Resultado | Causa | Test/subtest original |
| --- | --- | --- | --- |
| 1 | ERROR | A | `test_actual_timeout_replays_original_operation_identity (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_actual_timeout_replays_original_operation_identity)` |
| 2 | ERROR | A | `test_checkout_opens_shell_and_flushes_pending_before_enabling_payment (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_checkout_opens_shell_and_flushes_pending_before_enabling_payment)` |
| 3 | ERROR | A | `test_decimal_quantity_focus_scroll_and_tablet (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_decimal_quantity_focus_scroll_and_tablet)` |
| 4 | ERROR | A | `test_frame_latency_measured_separately_from_slow_http (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_frame_latency_measured_separately_from_slow_http)` |
| 5 | ERROR | A | `test_header_save_waits_without_false_cart_conflict (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_header_save_waits_without_false_cart_conflict)` |
| 6 | ERROR | A | `test_invalid_quantity_is_visible_and_blocks_checkout_until_fixed (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_invalid_quantity_is_visible_and_blocks_checkout_until_fixed)` |
| 7 | ERROR | A | `test_lost_response_timeout_replay_does_not_duplicate (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_lost_response_timeout_replay_does_not_duplicate)` |
| 8 | ERROR | A | `test_manual_price_editor_reconciles_grouped_rows (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_manual_price_editor_reconciles_grouped_rows)` |
| 9 | ERROR | A | `test_offline_retry_and_reload_durable_intents (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_offline_retry_and_reload_durable_intents)` |
| 10 | ERROR | A | `test_older_read_cannot_replace_newer_confirmed_cart (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_older_read_cannot_replace_newer_confirmed_cart)` |
| 11 | ERROR | A | `test_quantity_during_sync_then_delete (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_quantity_during_sync_then_delete)` |
| 12 | ERROR | A | `test_rejected_inactive_product_can_discard_pending (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_rejected_inactive_product_can_discard_pending)` |
| 13 | ERROR | A | `test_reload_preserves_add_quantity_delete_order_with_arbitrary_storage_iteration (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_reload_preserves_add_quantity_delete_order_with_arbitrary_storage_iteration)` |
| 14 | ERROR | A | `test_reload_unsent_intent_detects_changed_baseline (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_reload_unsent_intent_detects_changed_baseline)` |
| 15 | ERROR | A | `test_replayed_receipt_does_not_rebase_pending_quantity_over_other_tab (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_replayed_receipt_does_not_rebase_pending_quantity_over_other_tab)` |
| 16 | ERROR | A | `test_slow_response_does_not_block_visual_change_or_search (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_slow_response_does_not_block_visual_change_or_search)` |
| 17 | ERROR | A | `test_twenty_different_products_and_stable_dom (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_twenty_different_products_and_stable_dom)` |
| 18 | ERROR | A | `test_twenty_quantity_steps_coalesce_without_losing_units (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_twenty_quantity_steps_coalesce_without_losing_units)` |
| 19 | ERROR | A | `test_twenty_same_product_immediate_and_persisted (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_twenty_same_product_immediate_and_persisted)` |
| 20 | ERROR | A | `test_two_tabs_conflict_requires_explicit_resolution (e2e.browser_optimistic_cart.OptimisticCartBrowserTests.test_two_tabs_conflict_requires_explicit_resolution)` |
| 21 | ERROR | A | `test_abandon_warning_only_while_changes_are_unverified (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_abandon_warning_only_while_changes_are_unverified)` |
| 22 | ERROR | A | `test_batch_provisional_quantity_delete_dependencies (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_batch_provisional_quantity_delete_dependencies)` |
| 23 | ERROR | A | `test_close_reopen_cancels_only_local_flush_wait (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_close_reopen_cancels_only_local_flush_wait)` |
| 24 | ERROR | A | `test_corrupt_storage_blocks_editing_without_silent_fallback (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_corrupt_storage_blocks_editing_without_silent_fallback)` |
| 25 | ERROR | A | `test_expired_login_preserves_unknown_intent_until_same_user_revalidates (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_expired_login_preserves_unknown_intent_until_same_user_revalidates)` |
| 26 | ERROR | A | `test_fifty_clicks_one_atomic_request_preserves_snapshots (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_fifty_clicks_one_atomic_request_preserves_snapshots)` |
| 27 | ERROR | A | `test_forced_close_reopen_keeps_only_server_confirmed_state (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_forced_close_reopen_keeps_only_server_confirmed_state)` |
| 28 | ERROR | A | `test_header_http_error_requires_review (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_header_http_error_requires_review)` |
| 29 | ERROR | A | `test_header_network_abort_has_bounded_recovery (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_header_network_abort_has_bounded_recovery)` |
| 30 | ERROR | A | `test_header_timeout_clears_wait_but_blocks_checkout (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_header_timeout_clears_wait_but_blocks_checkout)` |
| 31 | ERROR | A | `test_incompatible_worker_or_identity_never_sends_pending_mutations (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_incompatible_worker_or_identity_never_sends_pending_mutations)` |
| 32 | ERROR | A | `test_invalid_flight_revision_is_quarantined_without_deletion (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_invalid_flight_revision_is_quarantined_without_deletion)` |
| 33 | ERROR | A | `test_keyboard_wedge_search_and_enter_preserve_units (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_keyboard_wedge_search_and_enter_preserve_units)` |
| 34 | ERROR | A | `test_lost_batch_response_reload_replays_original_envelope (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_lost_batch_response_reload_replays_original_envelope)` |
| 35 | ERROR | A | `test_namespace_never_imports_other_user_business_store_or_sale (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_namespace_never_imports_other_user_business_store_or_sale)` |
| 36 | ERROR | A | `test_partial_local_cleanup_restores_entire_committed_envelope (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_partial_local_cleanup_restores_entire_committed_envelope)` |
| 37 | ERROR | A | `test_quota_failure_before_envelope_send_is_recoverable (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_quota_failure_before_envelope_send_is_recoverable)` |
| 38 | ERROR | A | `test_stale_checkout_read_cannot_fill_reopened_modal (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_stale_checkout_read_cannot_fill_reopened_modal)` |
| 39 | ERROR | A | `test_stuck_busy_or_header_flag_has_bounded_flush (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_stuck_busy_or_header_flag_has_bounded_flush)` |
| 40 | ERROR | A | `test_unavailable_storage_quota_does_not_accept_a_click (e2e.browser_cart_hardening.HardenedCartBrowserTests.test_unavailable_storage_quota_does_not_accept_a_click)` |
| 41 | FAIL | B | `test_card_checkout_completes_with_dominant_new_sale_action (e2e.browser_checkout.BrowserCheckoutTests.test_card_checkout_completes_with_dominant_new_sale_action)` |
| 42 | FAIL | B | `test_cash_blank_insufficient_change_and_small_viewports (e2e.browser_checkout.BrowserCheckoutTests.test_cash_blank_insufficient_change_and_small_viewports) (viewport={'width': 1440, 'height': 900}, tender='')` |
| 43 | FAIL | C | `test_cash_blank_insufficient_change_and_small_viewports (e2e.browser_checkout.BrowserCheckoutTests.test_cash_blank_insufficient_change_and_small_viewports)` |
| 44 | FAIL | B | `test_cash_checkout_and_change_preview (e2e.browser_checkout.BrowserCheckoutTests.test_cash_checkout_and_change_preview)` |
| 45 | FAIL | B | `test_checkout_responsive_escape_and_focus_contract (e2e.browser_checkout.BrowserCheckoutTests.test_checkout_responsive_escape_and_focus_contract) (viewport={'width': 1440, 'height': 900})` |
| 46 | FAIL | B | `test_invalid_split_stays_open_and_preserves_idempotency_keys (e2e.browser_checkout.BrowserCheckoutTests.test_invalid_split_stays_open_and_preserves_idempotency_keys)` |
| 47 | FAIL | B | `test_non_cash_without_session_success_starts_new_sale_by_post (e2e.browser_checkout.BrowserCheckoutTests.test_non_cash_without_session_success_starts_new_sale_by_post)` |
| 48 | FAIL | B | `test_print_opens_fiscal_document_and_preserves_tpv (e2e.browser_checkout.BrowserCheckoutTests.test_print_opens_fiscal_document_and_preserves_tpv)` |
| 49 | FAIL | B | `test_server_500_keeps_modal_and_same_keys_for_safe_retry (e2e.browser_checkout.BrowserCheckoutTests.test_server_500_keeps_modal_and_same_keys_for_safe_retry)` |
| 50 | FAIL | B | `test_uncertain_checkout_validation_422_preserves_feedback_data_and_keys (e2e.browser_checkout.BrowserCheckoutTests.test_uncertain_checkout_validation_422_preserves_feedback_data_and_keys)` |
| 51 | FAIL | B | `test_uncertain_post_keeps_modal_and_same_keys_for_safe_retry (e2e.browser_checkout.BrowserCheckoutTests.test_uncertain_post_keeps_modal_and_same_keys_for_safe_retry)` |

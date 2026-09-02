// Run this once in the Scriptable app (tap the play button, not as a
// widget), then delete this script -- it contains the key in plaintext.
// It must match KEYCHAIN_ID in agent-usage-widget.js exactly.

const KEYCHAIN_ID = "agent-usage-widget-api-key";
const API_KEY = "enter_api_key_here";

Keychain.set(KEYCHAIN_ID, API_KEY);
console.log(`saved to Keychain: ${Keychain.contains(KEYCHAIN_ID)}`);
Script.complete();

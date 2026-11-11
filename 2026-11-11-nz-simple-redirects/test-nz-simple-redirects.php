<?php
/**
 * Offline tests for NZ Simple Redirects — no WordPress needed.
 *
 * Stubs the handful of WordPress functions the plugin calls at load time,
 * then exercises the pure matching/sanitising logic and the option-backed
 * add/delete helpers.
 *
 * Run: php test-nz-simple-redirects.php
 */

if ( ! defined( 'ABSPATH' ) ) {
    define( 'ABSPATH', '/tmp/wp/' );
}

// --- Minimal WordPress stubs ---------------------------------------
$GLOBALS['nzsr_test_options'] = array();

function get_option( $key, $default = false ) {
    return array_key_exists( $key, $GLOBALS['nzsr_test_options'] )
        ? $GLOBALS['nzsr_test_options'][ $key ]
        : $default;
}
function update_option( $key, $value ) {
    $GLOBALS['nzsr_test_options'][ $key ] = $value;
    return true;
}
function add_option( $key, $value ) {
    if ( ! array_key_exists( $key, $GLOBALS['nzsr_test_options'] ) ) {
        $GLOBALS['nzsr_test_options'][ $key ] = $value;
    }
    return true;
}
function delete_option( $key ) {
    unset( $GLOBALS['nzsr_test_options'][ $key ] );
    return true;
}
function add_action() {}
function add_filter() {}
function register_activation_hook() {}
function wp_unslash( $value ) { return $value; }
function home_url( $path = '' ) { return 'https://example.com' . $path; }
function wp_redirect() {}
function is_admin() { return false; }
function plugin_basename( $file ) { return basename( $file ); }
function admin_url( $path = '' ) { return 'https://example.com/wp-admin/' . $path; }
function esc_url( $url ) { return $url; }
function esc_html__( $text, $domain = null ) { return $text; }

require __DIR__ . '/nz-simple-redirects.php';

// --- Tiny test harness ---------------------------------------------
$pass = 0;
$fail = 0;

function check( $name, $condition ) {
    global $pass, $fail;
    if ( $condition ) {
        $pass++;
        echo "PASS: $name\n";
    } else {
        $fail++;
        echo "FAIL: $name\n";
    }
}

// --- nzsr_normalize_path -------------------------------------------
check( 'normalize adds leading slash', nzsr_normalize_path( 'old-page' ) === '/old-page' );
check( 'normalize strips trailing slash', nzsr_normalize_path( '/old-page/' ) === '/old-page' );
check( 'normalize lowercases', nzsr_normalize_path( '/Old-Page/' ) === '/old-page' );
check( 'normalize keeps root', nzsr_normalize_path( '/' ) === '/' );
check( 'normalize drops query string', nzsr_normalize_path( '/page/?utm_source=x' ) === '/page' );
check( 'normalize keeps wildcard', nzsr_normalize_path( '/blog/*/' ) === '/blog/*' );

// --- nzsr_match_redirect: exact ------------------------------------
$rules = array(
    array( 'from' => '/old-page', 'to' => '/new-page', 'code' => 301 ),
    array( 'from' => '/temp', 'to' => 'https://example.com/elsewhere', 'code' => 302 ),
    array( 'from' => '/blog/*', 'to' => '/news/*', 'code' => 301 ),
    array( 'from' => '/shop/*', 'to' => '/store', 'code' => 301 ),
);

$match = nzsr_match_redirect( '/old-page', $rules );
check( 'exact match returns target', $match !== null && $match['to'] === '/new-page' );
check( 'exact match returns 301', $match !== null && $match['code'] === 301 );
check( 'exact match ignores trailing slash', nzsr_match_redirect( '/old-page/', $rules ) !== null );
check( 'exact match ignores case', nzsr_match_redirect( '/OLD-PAGE', $rules ) !== null );

$match = nzsr_match_redirect( '/temp', $rules );
check( '302 code is preserved', $match !== null && $match['code'] === 302 );
check( 'absolute target kept', $match !== null && $match['to'] === 'https://example.com/elsewhere' );

check( 'no match returns null', nzsr_match_redirect( '/nothing-here', $rules ) === null );
check( 'empty rule list returns null', nzsr_match_redirect( '/old-page', array() ) === null );

// --- nzsr_match_redirect: wildcards --------------------------------
$match = nzsr_match_redirect( '/blog/hello-world', $rules );
check( 'wildcard substitutes remainder', $match !== null && $match['to'] === '/news/hello-world' );
check( 'wildcard keeps 301', $match !== null && $match['code'] === 301 );

$match = nzsr_match_redirect( '/shop/shoes/red', $rules );
check( 'wildcard without * in target uses target as-is', $match !== null && $match['to'] === '/store' );

check( 'wildcard does not match bare prefix', nzsr_match_redirect( '/blog', $rules ) === null );

$longest = array(
    array( 'from' => '/a/*', 'to' => '/x/*', 'code' => 301 ),
    array( 'from' => '/a/b/*', 'to' => '/y/*', 'code' => 301 ),
);
$match = nzsr_match_redirect( '/a/b/c', $longest );
check( 'longest wildcard prefix wins', $match !== null && $match['to'] === '/y/c' );

// --- nzsr_sanitize_rule --------------------------------------------
check( 'sanitize accepts relative target', nzsr_sanitize_rule( '/a', '/b', 301 ) !== null );
check( 'sanitize accepts absolute target', nzsr_sanitize_rule( '/a', 'https://example.com/b', 301 ) !== null );
check( 'sanitize rejects empty from', nzsr_sanitize_rule( '', '/b', 301 ) === null );
check( 'sanitize rejects root from', nzsr_sanitize_rule( '/', '/b', 301 ) === null );
check( 'sanitize rejects empty to', nzsr_sanitize_rule( '/a', '', 301 ) === null );
check( 'sanitize rejects javascript: target', nzsr_sanitize_rule( '/a', 'javascript:alert(1)', 301 ) === null );
check( 'sanitize rejects bare word target', nzsr_sanitize_rule( '/a', 'new-page', 301 ) === null );
check( 'sanitize coerces bad code to 301', nzsr_sanitize_rule( '/a', '/b', 999 )['code'] === 301 );

// --- add / delete round-trip (stubbed options) ----------------------
$GLOBALS['nzsr_test_options'] = array();

check( 'add stores a rule', nzsr_add_redirect( '/one', '/two', 301 ) && count( nzsr_get_redirects() ) === 1 );
check( 'add second rule', nzsr_add_redirect( '/three', '/four', 302 ) && count( nzsr_get_redirects() ) === 2 );
check( 'add duplicate from updates in place', nzsr_add_redirect( '/one', '/two-new', 302 ) && count( nzsr_get_redirects() ) === 2 );
$stored = nzsr_get_redirects();
check( 'duplicate update kept new target', $stored[0]['to'] === '/two-new' && $stored[0]['code'] === 302 );
check( 'add invalid rule is rejected', nzsr_add_redirect( '/', '/x', 301 ) === false );
check( 'delete removes a rule', nzsr_delete_redirect( '/three' ) && count( nzsr_get_redirects() ) === 1 );
check( 'delete missing rule returns false', nzsr_delete_redirect( '/nope' ) === false );

// --- Summary ---------------------------------------------------------
echo "\n$pass passed, $fail failed\n";
exit( $fail === 0 ? 0 : 1 );

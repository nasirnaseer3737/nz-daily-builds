<?php
/**
 * Plugin Name:       NZ Simple Redirects
 * Plugin URI:        https://github.com/nasirnaseer3737/nz-daily-builds
 * Description:       A lightweight 301/302 redirect manager for WordPress. Add redirects from the Settings screen — exact paths and /* wildcards — no .htaccess editing, no bloat.
 * Version:           1.0.0
 * Requires at least: 5.8
 * Requires PHP:      7.4
 * Author:            Nasir Naseer
 * Author URI:        https://nzgenix.digital
 * License:           GPLv2 or later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       nz-simple-redirects
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

define( 'NZSR_VERSION', '1.0.0' );
define( 'NZSR_OPTION', 'nzsr_redirects' );
define( 'NZSR_MENU_SLUG', 'nz-simple-redirects' );

/* ------------------------------------------------------------------ */
/*  Pure helpers — no WordPress calls, unit-testable                   */
/* ------------------------------------------------------------------ */

/**
 * Normalise a "from" path for storage and comparison.
 *
 * - Forces a leading slash, strips a trailing slash (except root).
 * - Drops any query string or fragment.
 * - Lowercases, so /Old-Page and /old-page are the same rule.
 * - Keeps a trailing /* wildcard intact.
 *
 * @param string $path Raw path, e.g. "old-page/", "/Old-Page/?utm=x".
 * @return string Normalised path, e.g. "/old-page".
 */
function nzsr_normalize_path( $path ) {
    $path = trim( (string) $path );
    $path = strtok( $path, '?#' ); // drop query string / fragment
    $path = str_replace( '\\', '/', $path );
    $path = '/' . ltrim( $path, '/' );
    if ( strlen( $path ) > 1 ) {
        $path = rtrim( $path, '/' );
    }
    return strtolower( $path );
}

/**
 * Match a request path against the redirect rules.
 *
 * Exact matches win first. Wildcard rules (from ending in /*) are checked
 * second, longest prefix wins, and a * in the "to" value is replaced with
 * the matched remainder of the path.
 *
 * @param string $request_path Request path, e.g. "/blog/hello-world".
 * @param array  $redirects    Rules, each ['from' => ..., 'to' => ..., 'code' => 301|302].
 * @return array|null ['to' => string, 'code' => int] or null when nothing matches.
 */
function nzsr_match_redirect( $request_path, $redirects ) {
    $request = nzsr_normalize_path( $request_path );

    if ( ! is_array( $redirects ) || $redirects === array() ) {
        return null;
    }

    // Pass 1: exact match.
    foreach ( $redirects as $rule ) {
        if ( ! isset( $rule['from'], $rule['to'] ) ) {
            continue;
        }
        $from = nzsr_normalize_path( $rule['from'] );
        if ( substr( $from, -2 ) === '/*' ) {
            continue; // wildcards are handled in pass 2
        }
        if ( $from === $request ) {
            return array(
                'to'   => $rule['to'],
                'code' => isset( $rule['code'] ) ? (int) $rule['code'] : 301,
            );
        }
    }

    // Pass 2: wildcard match — longest prefix wins.
    $best     = null;
    $best_len = -1;
    foreach ( $redirects as $rule ) {
        if ( ! isset( $rule['from'], $rule['to'] ) ) {
            continue;
        }
        $from = nzsr_normalize_path( $rule['from'] );
        if ( substr( $from, -2 ) !== '/*' ) {
            continue;
        }
        $prefix = substr( $from, 0, -1 ); // "/blog/" (keeps trailing slash)
        if ( strpos( $request, $prefix ) !== 0 ) {
            continue;
        }
        $rest = substr( $request, strlen( $prefix ) );
        if ( $rest === '' ) {
            continue; // "/blog/" alone is not a wildcard hit
        }
        if ( strlen( $prefix ) <= $best_len ) {
            continue;
        }
        $to = $rule['to'];
        if ( strpos( $to, '*' ) !== false ) {
            $to = str_replace( '*', $rest, $to );
        }
        $best     = array(
            'to'   => $to,
            'code' => isset( $rule['code'] ) ? (int) $rule['code'] : 301,
        );
        $best_len = strlen( $prefix );
    }

    return $best;
}

/**
 * Validate and sanitise one redirect rule.
 *
 * The "to" value must be a site-relative path ("/new-page") or an absolute
 * http(s) URL. Anything else (javascript:, empty, root "/") is rejected.
 *
 * @param string $from Source path.
 * @param string $to   Target path or URL.
 * @param int    $code 301 or 302 (anything else becomes 301).
 * @return array|null Clean rule ['from', 'to', 'code'] or null when invalid.
 */
function nzsr_sanitize_rule( $from, $to, $code ) {
    $from = nzsr_normalize_path( $from );
    if ( $from === '/' || $from === '' ) {
        return null;
    }

    $to = trim( (string) $to );
    if ( $to === '' ) {
        return null;
    }
    if ( strpos( $to, '/' ) === 0 ) {
        // Site-relative target — allowed as-is.
    } elseif ( preg_match( '#^https?://#i', $to ) ) {
        // Absolute http(s) target — allowed as-is.
    } else {
        return null;
    }

    $code = (int) $code;
    if ( $code !== 301 && $code !== 302 ) {
        $code = 301;
    }

    return array(
        'from' => $from,
        'to'   => $to,
        'code' => $code,
    );
}

/* ------------------------------------------------------------------ */
/*  Storage                                                            */
/* ------------------------------------------------------------------ */

/**
 * Get all stored redirect rules.
 *
 * @return array List of ['from', 'to', 'code'] rules.
 */
function nzsr_get_redirects() {
    $rules = get_option( NZSR_OPTION, array() );
    return is_array( $rules ) ? $rules : array();
}

/**
 * Add a redirect rule (updates in place when the "from" already exists).
 *
 * @param string $from Source path.
 * @param string $to   Target path or URL.
 * @param int    $code 301 or 302.
 * @return bool True on success, false when the rule is invalid.
 */
function nzsr_add_redirect( $from, $to, $code = 301 ) {
    $rule = nzsr_sanitize_rule( $from, $to, $code );
    if ( $rule === null ) {
        return false;
    }

    $rules = nzsr_get_redirects();
    foreach ( $rules as $i => $existing ) {
        if ( isset( $existing['from'] )
            && nzsr_normalize_path( $existing['from'] ) === $rule['from']
        ) {
            $rules[ $i ] = $rule;
            update_option( NZSR_OPTION, $rules );
            return true;
        }
    }

    $rules[] = $rule;
    update_option( NZSR_OPTION, $rules );
    return true;
}

/**
 * Delete the rule for a "from" path.
 *
 * @param string $from Source path.
 * @return bool True when a rule was removed.
 */
function nzsr_delete_redirect( $from ) {
    $from  = nzsr_normalize_path( $from );
    $rules = nzsr_get_redirects();
    $kept  = array();
    $found = false;

    foreach ( $rules as $rule ) {
        if ( isset( $rule['from'] )
            && nzsr_normalize_path( $rule['from'] ) === $from
        ) {
            $found = true;
            continue;
        }
        $kept[] = $rule;
    }

    if ( $found ) {
        update_option( NZSR_OPTION, $kept );
    }
    return $found;
}

/* ------------------------------------------------------------------ */
/*  Front-end redirect                                                 */
/* ------------------------------------------------------------------ */

/**
 * Run on template_redirect: match the current request and redirect.
 */
function nzsr_maybe_redirect() {
    if ( is_admin() ) {
        return;
    }

    $request_uri = isset( $_SERVER['REQUEST_URI'] )
        ? wp_unslash( $_SERVER['REQUEST_URI'] )
        : '';
    $path = parse_url( $request_uri, PHP_URL_PATH );
    if ( $path === null || $path === false ) {
        $path = '/';
    }

    $match = nzsr_match_redirect( $path, nzsr_get_redirects() );
    if ( $match === null ) {
        return;
    }

    $to = $match['to'];
    if ( strpos( $to, '/' ) === 0 ) {
        $to = home_url( $to );
    }

    wp_redirect( $to, $match['code'] );
    exit;
}
add_action( 'template_redirect', 'nzsr_maybe_redirect' );

/* ------------------------------------------------------------------ */
/*  Admin screen — Settings > NZ Redirects                             */
/* ------------------------------------------------------------------ */

function nzsr_admin_menu() {
    add_options_page(
        __( 'NZ Redirects', 'nz-simple-redirects' ),
        __( 'NZ Redirects', 'nz-simple-redirects' ),
        'manage_options',
        NZSR_MENU_SLUG,
        'nzsr_render_admin_page'
    );
}
add_action( 'admin_menu', 'nzsr_admin_menu' );

/**
 * Handle the add / delete form posts on the admin screen.
 */
function nzsr_handle_admin_post() {
    if ( ! current_user_can( 'manage_options' ) ) {
        return;
    }
    if ( ! isset( $_POST['nzsr_action'] ) ) {
        return;
    }
    check_admin_referer( 'nzsr_admin' );

    if ( $_POST['nzsr_action'] === 'add' ) {
        nzsr_add_redirect(
            isset( $_POST['nzsr_from'] ) ? wp_unslash( $_POST['nzsr_from'] ) : '',
            isset( $_POST['nzsr_to'] ) ? wp_unslash( $_POST['nzsr_to'] ) : '',
            isset( $_POST['nzsr_code'] ) ? (int) $_POST['nzsr_code'] : 301
        );
    } elseif ( $_POST['nzsr_action'] === 'delete' && isset( $_POST['nzsr_from'] ) ) {
        nzsr_delete_redirect( wp_unslash( $_POST['nzsr_from'] ) );
    }
}
add_action( 'admin_init', 'nzsr_handle_admin_post' );

function nzsr_render_admin_page() {
    $rules = nzsr_get_redirects();
    ?>
    <div class="wrap">
        <h1><?php esc_html_e( 'NZ Simple Redirects', 'nz-simple-redirects' ); ?></h1>
        <p><?php esc_html_e( 'Redirect old URLs to new ones. Use /* at the end of a "from" path to redirect a whole section, and * in the "to" value to keep the rest of the path.', 'nz-simple-redirects' ); ?></p>
        <p><em><?php esc_html_e( 'Example: from /blog/* to /news/* sends /blog/hello to /news/hello.', 'nz-simple-redirects' ); ?></em></p>

        <h2><?php esc_html_e( 'Add redirect', 'nz-simple-redirects' ); ?></h2>
        <form method="post" action="">
            <?php wp_nonce_field( 'nzsr_admin' ); ?>
            <input type="hidden" name="nzsr_action" value="add" />
            <table class="form-table">
                <tr>
                    <th><label for="nzsr_from"><?php esc_html_e( 'From', 'nz-simple-redirects' ); ?></label></th>
                    <td><input type="text" id="nzsr_from" name="nzsr_from" class="regular-text" placeholder="/old-page" required />
                    <p class="description"><?php esc_html_e( 'Site path, e.g. /old-page or /blog/*', 'nz-simple-redirects' ); ?></p></td>
                </tr>
                <tr>
                    <th><label for="nzsr_to"><?php esc_html_e( 'To', 'nz-simple-redirects' ); ?></label></th>
                    <td><input type="text" id="nzsr_to" name="nzsr_to" class="regular-text" placeholder="/new-page" required />
                    <p class="description"><?php esc_html_e( 'Site path (/new-page) or full URL (https://example.com/new-page)', 'nz-simple-redirects' ); ?></p></td>
                </tr>
                <tr>
                    <th><label for="nzsr_code"><?php esc_html_e( 'Type', 'nz-simple-redirects' ); ?></label></th>
                    <td>
                        <select id="nzsr_code" name="nzsr_code">
                            <option value="301">301 — Permanent</option>
                            <option value="302">302 — Temporary</option>
                        </select>
                    </td>
                </tr>
            </table>
            <?php submit_button( __( 'Add redirect', 'nz-simple-redirects' ) ); ?>
        </form>

        <h2><?php esc_html_e( 'Current redirects', 'nz-simple-redirects' ); ?></h2>
        <?php if ( $rules === array() ) : ?>
            <p><?php esc_html_e( 'No redirects yet.', 'nz-simple-redirects' ); ?></p>
        <?php else : ?>
            <table class="widefat striped">
                <thead>
                    <tr>
                        <th><?php esc_html_e( 'From', 'nz-simple-redirects' ); ?></th>
                        <th><?php esc_html_e( 'To', 'nz-simple-redirects' ); ?></th>
                        <th><?php esc_html_e( 'Type', 'nz-simple-redirects' ); ?></th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ( $rules as $rule ) : ?>
                        <tr>
                            <td><code><?php echo esc_html( $rule['from'] ); ?></code></td>
                            <td><code><?php echo esc_html( $rule['to'] ); ?></code></td>
                            <td><?php echo (int) $rule['code']; ?></td>
                            <td>
                                <form method="post" action="" style="margin:0">
                                    <?php wp_nonce_field( 'nzsr_admin' ); ?>
                                    <input type="hidden" name="nzsr_action" value="delete" />
                                    <input type="hidden" name="nzsr_from" value="<?php echo esc_attr( $rule['from'] ); ?>" />
                                    <?php submit_button( __( 'Delete', 'nz-simple-redirects' ), 'delete small', '', false ); ?>
                                </form>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        <?php endif; ?>
    </div>
    <?php
}

/**
 * Add a "Settings" link on the Plugins screen.
 */
function nzsr_plugin_action_links( $links ) {
    $links[] = sprintf(
        '<a href="%s">%s</a>',
        esc_url( admin_url( 'options-general.php?page=' . NZSR_MENU_SLUG ) ),
        esc_html__( 'Settings', 'nz-simple-redirects' )
    );
    return $links;
}
add_filter( 'plugin_action_links_' . plugin_basename( __FILE__ ), 'nzsr_plugin_action_links' );

/**
 * Create the (empty) option on activation so the admin screen always works.
 */
function nzsr_activate() {
    if ( get_option( NZSR_OPTION, null ) === null ) {
        add_option( NZSR_OPTION, array() );
    }
}
register_activation_hook( __FILE__, 'nzsr_activate' );

// bbe_render.h — raylib spectator renderer for the Blood Bowl env.
//
// Two rendering paths:
//   * FFB art (default): the actual FUMBBL client art — pitch background,
//     per-position player sprite sheets, status overlays — staged into
//     resources/bloodbowl/ by tools/stage_spectator_art.py. Sheet format
//     (FFB PlayerIconFactory): 4 columns [home, home-active, away,
//     away-active], cell = width/4, rows = cosmetic variants.
//   * Fallback circles: when art is missing (remote boxes, BBE_ART_DIR
//     unset and resources/ absent) we degrade to the original token look.
//
// Drawn once per c_render() call (one frame per decision step); SetTargetFPS
// paces playback, so render_fps == decisions/sec. Training never calls
// c_render. Closing the window exits the process with code 7
// (tools/spectate.sh stops its loop on that).
#pragma once

#include <stdio.h>
#include "raylib.h"

// FFB native geometry: 30px squares, pitch image 782x452 (26x15 + 1px border).
// Everything is multiplied by bbe_scale (BBE_SCALE env var, default 1.6) so
// the window reads comfortably on hidpi screens.
#define BBE_CELL 30
#define BBE_MARGIN 20
#define BBE_HUD_H 64
#define BBE_PITCH_W 782
#define BBE_PITCH_H 452

static float bbe_scale = 1.6f;

#define BBE_S(v) ((int)((v) * bbe_scale + 0.5f))
#define BBE_WIN_W (BBE_S(BBE_PITCH_W) + 2 * BBE_MARGIN)
#define BBE_WIN_H (BBE_S(BBE_PITCH_H) + BBE_S(BBE_HUD_H) + 2 * BBE_MARGIN)

typedef struct {
    char banner[256];
    bool art_ok;
    char art_dir[512];
    Texture2D pitch, ball, holdball, prone, stunned;
    Texture2D disk_normal[2], disk_large[2], disk_small[2]; // [home, away]
    Texture2D icon[BB_TEAM_COUNT][BB_MAX_POSITIONS];
    bool icon_tried[BB_TEAM_COUNT][BB_MAX_POSITIONS];
    char icon_rel[BB_TEAM_COUNT][BB_MAX_POSITIONS][80];
} BBEClient;

static const Color BBE_GRASS_A = {38, 110, 52, 255};
static const Color BBE_GRASS_B = {34, 100, 47, 255};
static const Color BBE_LINE = {235, 235, 225, 170};
static const Color BBE_HOME = {196, 48, 56, 255};   // crimson
static const Color BBE_AWAY = {52, 92, 196, 255};   // blue
static const Color BBE_BALL = {150, 92, 28, 255};
static const Color BBE_GOLD = {255, 204, 64, 255};

static int bbe_px(int x) { return BBE_MARGIN + BBE_S(1 + x * BBE_CELL); }
static int bbe_py(int y) { return BBE_MARGIN + BBE_S(BBE_HUD_H + 1 + y * BBE_CELL); }
static int bbe_cell(void) { return BBE_S(BBE_CELL); }

static Texture2D bbe_load(const BBEClient* c, const char* rel) {
    char path[640];
    snprintf(path, sizeof(path), "%s/%s", c->art_dir, rel);
    return LoadTexture(path); // missing file -> id 0 (graceful)
}

static void bbe_load_iconmap(BBEClient* c) {
    char path[640];
    snprintf(path, sizeof(path), "%s/iconmap.txt", c->art_dir);
    FILE* f = fopen(path, "r");
    if (!f) return;
    int ti, pi;
    char rel[80];
    while (fscanf(f, "%d %d %79s", &ti, &pi, rel) == 3) {
        if (ti >= 0 && ti < BB_TEAM_COUNT && pi >= 0 && pi < BB_MAX_POSITIONS) {
            snprintf(c->icon_rel[ti][pi], sizeof(c->icon_rel[ti][pi]), "%s", rel);
        }
    }
    fclose(f);
}

static void bbe_render_init(Bloodbowl* env) {
    BBEClient* c = (BBEClient*)calloc(1, sizeof(BBEClient));
    const char* banner = getenv("BBE_BANNER");
    snprintf(c->banner, sizeof(c->banner), "%s", banner ? banner : "live policy");
    env->client = c;
    const char* sc = getenv("BBE_SCALE");
    if (sc) {
        float v = (float)atof(sc);
        if (v >= 1.0f && v <= 3.0f) bbe_scale = v;
    }
    InitWindow(BBE_WIN_W, BBE_WIN_H, "Blood Bowl RL — spectator");
    SetTargetFPS(env->render_fps > 0 ? env->render_fps : 60);

    // Art root: explicit env var, else the PufferLib cwd convention.
    const char* art = getenv("BBE_ART_DIR");
    snprintf(c->art_dir, sizeof(c->art_dir), "%s", art ? art : "resources/bloodbowl");
    c->pitch = bbe_load(c, "pitch.png");
    if (c->pitch.id != 0) {
        c->art_ok = true;
        // Non-integer upscale: bilinear keeps the pitch smooth; sprites stay
        // acceptable (slightly soft beats unevenly-doubled pixels).
        if (bbe_scale != 1.0f) SetTextureFilter(c->pitch, TEXTURE_FILTER_BILINEAR);
        c->ball = bbe_load(c, "sball_30x30.png");
        c->holdball = bbe_load(c, "holdball.png");
        c->prone = bbe_load(c, "prone.gif");
        c->stunned = bbe_load(c, "stunned.gif");
        c->disk_normal[0] = bbe_load(c, "normalHome.png");
        c->disk_normal[1] = bbe_load(c, "normalAway.png");
        c->disk_large[0] = bbe_load(c, "largeHome.png");
        c->disk_large[1] = bbe_load(c, "largeAway.png");
        c->disk_small[0] = bbe_load(c, "smallHome.png");
        c->disk_small[1] = bbe_load(c, "smallAway.png");
        bbe_load_iconmap(c);
    }
}

// Lazy per-position iconset load; id 0 when unavailable.
static Texture2D bbe_iconset(BBEClient* c, int team_id, int pos_id) {
    if (team_id < 0 || team_id >= BB_TEAM_COUNT || pos_id < 0 ||
        pos_id >= BB_MAX_POSITIONS) {
        return (Texture2D){0};
    }
    if (!c->icon_tried[team_id][pos_id]) {
        c->icon_tried[team_id][pos_id] = true;
        if (c->icon_rel[team_id][pos_id][0]) {
            c->icon[team_id][pos_id] = bbe_load(c, c->icon_rel[team_id][pos_id]);
        }
    }
    return c->icon[team_id][pos_id];
}

// ---------------------------------------------------------------------------
// Fallback path: procedural pitch + colored tokens (original look).
// ---------------------------------------------------------------------------
static void bbe_draw_pitch_fallback(void) {
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            Color g = ((x + y) & 1) ? BBE_GRASS_A : BBE_GRASS_B;
            if (x == 0) g = (Color){88, 64, 60, 255};
            if (x == BB_PITCH_LEN - 1) g = (Color){56, 66, 96, 255};
            DrawRectangle(bbe_px(x), bbe_py(y), bbe_cell(), bbe_cell(), g);
        }
    }
    DrawLineEx((Vector2){(float)bbe_px(13), (float)bbe_py(0)},
               (Vector2){(float)bbe_px(13), (float)bbe_py(BB_PITCH_WID)}, 3, BBE_LINE);
    DrawLineEx((Vector2){(float)bbe_px(0), (float)bbe_py(4)},
               (Vector2){(float)bbe_px(BB_PITCH_LEN), (float)bbe_py(4)}, 2, Fade(BBE_LINE, 0.5f));
    DrawLineEx((Vector2){(float)bbe_px(0), (float)bbe_py(11)},
               (Vector2){(float)bbe_px(BB_PITCH_LEN), (float)bbe_py(11)}, 2, Fade(BBE_LINE, 0.5f));
}

static void bbe_draw_player_fallback(const bb_match* m, int s) {
    const bb_player* p = &m->players[s];
    int team = BB_TEAM_OF(s);
    int cx = bbe_px(p->x) + bbe_cell() / 2;
    int cy = bbe_py(p->y) + bbe_cell() / 2;
    Color col = team == BB_HOME ? BBE_HOME : BBE_AWAY;
    bool down = p->stance != BB_STANCE_STANDING;
    bool stunned = p->stance == BB_STANCE_STUNNED || p->stance == BB_STANCE_STUNNED_USED;
    if (down) col = Fade(col, 0.55f);
    DrawCircle(cx, cy, bbe_cell() * 0.38f, col);
    DrawCircleLines(cx, cy, bbe_cell() * 0.38f, Fade(BLACK, 0.6f));
    if (down) {
        DrawLineEx((Vector2){(float)(cx - 10), (float)cy}, (Vector2){(float)(cx + 10), (float)cy},
                   3, RAYWHITE);
        if (stunned) {
            DrawLineEx((Vector2){(float)cx, (float)(cy - 10)}, (Vector2){(float)cx, (float)(cy + 10)},
                       3, RAYWHITE);
        }
    }
    char num[4];
    snprintf(num, sizeof(num), "%d", BB_SLOT_OF(s) + 1);
    int tw = MeasureText(num, 10);
    DrawText(num, cx - tw / 2, cy - 5, 10, RAYWHITE);
    if (p->flags & BB_PF_HAS_BALL) {
        DrawCircleLines(cx, cy, bbe_cell() * 0.46f, BBE_GOLD);
        DrawCircle(cx + 9, cy - 9, 5, BBE_BALL);
        DrawCircleLines(cx + 9, cy - 9, 5, RAYWHITE);
    }
}

// ---------------------------------------------------------------------------
// FFB-art path.
// ---------------------------------------------------------------------------
static void bbe_draw_player_art(BBEClient* c, const bb_match* m, int s, int active_slot) {
    const bb_player* p = &m->players[s];
    int team = BB_TEAM_OF(s);
    int cx = bbe_px(p->x) + bbe_cell() / 2;
    int cy = bbe_py(p->y) + bbe_cell() / 2;
    bool down = p->stance != BB_STANCE_STANDING;
    bool stunned = p->stance == BB_STANCE_STUNNED || p->stance == BB_STANCE_STUNNED_USED;
    bool active = s == active_slot;

    Texture2D sheet = bbe_iconset(c, m->team_id[team], p->position_id);
    if (sheet.id != 0) {
        int cell = sheet.width / 4;
        int rows = cell > 0 ? sheet.height / cell : 0;
        int row = rows > 0 ? BB_SLOT_OF(s) % rows : 0;
        int col = (team == BB_HOME ? 0 : 2) + (active ? 1 : 0);
        Rectangle src = {(float)(col * cell), (float)(row * cell), (float)cell, (float)cell};
        // Native size, centered on the square (FFB look; big guys overlap).
        Rectangle dst = {(float)cx, (float)cy, cell * bbe_scale, cell * bbe_scale};
        Vector2 origin = {cell * bbe_scale / 2.0f, cell * bbe_scale / 2.0f};
        DrawTexturePro(sheet, src, dst, origin, 0, down ? Fade(WHITE, 0.8f) : WHITE);
    } else {
        // Star/unmapped: FFB's abstract disk + shirt number.
        Texture2D disk = c->disk_normal[team];
        if (disk.id != 0) {
            DrawTextureEx(disk,
                          (Vector2){cx - disk.width * bbe_scale / 2,
                                    cy - disk.height * bbe_scale / 2},
                          0, bbe_scale, down ? Fade(WHITE, 0.8f) : WHITE);
        }
        char num[4];
        snprintf(num, sizeof(num), "%d", BB_SLOT_OF(s) + 1);
        int tw = MeasureText(num, 10);
        DrawText(num, cx - tw / 2, cy - 5, 10, RAYWHITE);
    }
    // FFB convention: standing sprite + status overlay (no rotation).
    if (down) {
        Texture2D ov = stunned ? c->stunned : c->prone;
        if (ov.id != 0) {
            DrawTextureEx(ov,
                          (Vector2){cx - ov.width * bbe_scale / 2,
                                    cy - ov.height * bbe_scale / 2},
                          0, bbe_scale, WHITE);
        }
    }
    if (p->flags & BB_PF_HAS_BALL && c->holdball.id != 0) {
        DrawTextureEx(c->holdball, (Vector2){(float)bbe_px(p->x), (float)bbe_py(p->y)},
                      0, bbe_scale, WHITE);
    }
}

static void bbe_draw_ball_art(const BBEClient* c, const bb_match* m) {
    if (m->ball.state != BB_BALL_ON_GROUND && m->ball.state != BB_BALL_IN_AIR) return;
    int x = bbe_px(m->ball.x);
    int y = bbe_py(m->ball.y);
    if (c->ball.id != 0) {
        DrawTextureEx(c->ball, (Vector2){(float)x, (float)y}, 0, bbe_scale,
                      m->ball.state == BB_BALL_IN_AIR ? Fade(WHITE, 0.6f) : WHITE);
        if (m->ball.state == BB_BALL_IN_AIR) {
            DrawCircleLines(x + bbe_cell() / 2, y + bbe_cell() / 2, BBE_S(12), BBE_GOLD);
        }
    } else {
        DrawCircle(x + bbe_cell() / 2, y + bbe_cell() / 2, BBE_S(6), BBE_BALL);
    }
}

static void bbe_draw_ball_fallback(const bb_match* m) {
    if (m->ball.state != BB_BALL_ON_GROUND && m->ball.state != BB_BALL_IN_AIR) return;
    int cx = bbe_px(m->ball.x) + bbe_cell() / 2;
    int cy = bbe_py(m->ball.y) + bbe_cell() / 2;
    if (m->ball.state == BB_BALL_IN_AIR) {
        DrawCircleLines(cx, cy, 7, BBE_GOLD);
    } else {
        DrawCircle(cx, cy, 6, BBE_BALL);
        DrawCircleLines(cx, cy, 6, RAYWHITE);
    }
}

static void bbe_draw_hud(const Bloodbowl* env) {
    const bb_match* m = &env->match;
    const BBEClient* c = (const BBEClient*)env->client;
    char buf[256];

    const char* home = bb_team_defs[m->team_id[BB_HOME]].display;
    const char* away = bb_team_defs[m->team_id[BB_AWAY]].display;

    DrawRectangle(0, 0, BBE_WIN_W, BBE_S(BBE_HUD_H) + BBE_MARGIN - 4, (Color){24, 26, 30, 255});

    snprintf(buf, sizeof(buf), "%s%s  %d - %d  %s%s",
             m->decision_team == BB_HOME ? "> " : "  ", home,
             m->score[BB_HOME], m->score[BB_AWAY], away,
             m->decision_team == BB_AWAY ? " <" : "  ");
    int f1 = BBE_S(20);
    DrawText(buf, BBE_MARGIN, BBE_S(10), f1, RAYWHITE);
    DrawCircle(BBE_MARGIN - 8, BBE_S(20), 5, BBE_HOME);
    DrawCircle(BBE_MARGIN + MeasureText(buf, f1) + 10, BBE_S(20), 5, BBE_AWAY);

    snprintf(buf, sizeof(buf), "half %d   turn %d/%d   decision %d   %s",
             m->half, m->turn[0], m->turn[1], env->decisions, c->banner);
    DrawText(buf, BBE_MARGIN, BBE_S(38), BBE_S(10), (Color){170, 175, 185, 255});
}

static void bbe_render_draw(Bloodbowl* env) {
    if (env->client == NULL) bbe_render_init(env);
    BBEClient* c = (BBEClient*)env->client;
    if (WindowShouldClose()) {
        CloseWindow();
        exit(7); // spectate.sh: user closed the window -> stop the loop
    }
    const bb_match* m = &env->match;
    // The currently acting player (frame top a) gets the "active" sprite pose.
    const bb_frame* top = m->stack_top ? &m->stack[m->stack_top - 1] : 0;
    int active_slot = (top && top->a < BB_NUM_PLAYERS) ? top->a : -1;

    BeginDrawing();
    ClearBackground((Color){24, 26, 30, 255});
    if (c->art_ok) {
        DrawTextureEx(c->pitch, (Vector2){BBE_MARGIN, (float)(BBE_MARGIN + BBE_S(BBE_HUD_H))},
                      0, bbe_scale, WHITE);
        bbe_draw_ball_art(c, m);
        // Draw downed players first so standing players read on top.
        for (int pass = 0; pass < 2; pass++) {
            for (int s = 0; s < BB_NUM_PLAYERS; s++) {
                const bb_player* p = &m->players[s];
                if (p->location != BB_LOC_ON_PITCH) continue;
                bool down = p->stance != BB_STANCE_STANDING;
                if ((pass == 0) == down) bbe_draw_player_art(c, m, s, active_slot);
            }
        }
    } else {
        bbe_draw_pitch_fallback();
        bbe_draw_ball_fallback(m);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            if (m->players[s].location == BB_LOC_ON_PITCH) bbe_draw_player_fallback(m, s);
        }
    }
    bbe_draw_hud(env);
    EndDrawing();
}

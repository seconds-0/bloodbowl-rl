// bbe_render.h — raylib spectator renderer for the Blood Bowl env.
//
// Drawn once per c_render() call (one frame per decision step); SetTargetFPS
// paces playback, so render_fps == decisions/sec. Training never calls
// c_render, so the GPU box pays nothing for this. Closing the window exits
// the process with code 7 (tools/spectate.sh stops its loop on that).
//
// Always home = crimson playing left-to-right, away = blue right-to-left;
// the real roster identities are in the HUD (bb_team_defs display names).
#pragma once

#include <stdio.h>
#include "raylib.h"

#define BBE_CELL 34
#define BBE_MARGIN 20
#define BBE_HUD_H 64
#define BBE_WIN_W (BB_PITCH_LEN * BBE_CELL + 2 * BBE_MARGIN)
#define BBE_WIN_H (BB_PITCH_WID * BBE_CELL + BBE_HUD_H + 2 * BBE_MARGIN)

typedef struct {
    char banner[256];
} BBEClient;

static const Color BBE_GRASS_A = {38, 110, 52, 255};
static const Color BBE_GRASS_B = {34, 100, 47, 255};
static const Color BBE_LINE = {235, 235, 225, 170};
static const Color BBE_HOME = {196, 48, 56, 255};   // crimson
static const Color BBE_AWAY = {52, 92, 196, 255};   // blue
static const Color BBE_BALL = {150, 92, 28, 255};
static const Color BBE_GOLD = {255, 204, 64, 255};

static int bbe_px(int x) { return BBE_MARGIN + x * BBE_CELL; }
static int bbe_py(int y) { return BBE_MARGIN + BBE_HUD_H + y * BBE_CELL; }

static void bbe_render_init(Bloodbowl* env) {
    BBEClient* c = (BBEClient*)calloc(1, sizeof(BBEClient));
    const char* banner = getenv("BBE_BANNER");
    snprintf(c->banner, sizeof(c->banner), "%s", banner ? banner : "live policy");
    env->client = c;
    InitWindow(BBE_WIN_W, BBE_WIN_H, "Blood Bowl RL — spectator");
    SetTargetFPS(env->render_fps > 0 ? env->render_fps : 60);
}

static void bbe_draw_pitch(void) {
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            Color g = ((x + y) & 1) ? BBE_GRASS_A : BBE_GRASS_B;
            // End zones tinted toward each team's colour.
            if (x == 0) g = (Color){88, 64, 60, 255};
            if (x == BB_PITCH_LEN - 1) g = (Color){56, 66, 96, 255};
            DrawRectangle(bbe_px(x), bbe_py(y), BBE_CELL, BBE_CELL, g);
        }
    }
    // Grid.
    for (int x = 0; x <= BB_PITCH_LEN; x++) {
        DrawLine(bbe_px(x), bbe_py(0), bbe_px(x), bbe_py(BB_PITCH_WID), Fade(BBE_LINE, 0.12f));
    }
    for (int y = 0; y <= BB_PITCH_WID; y++) {
        DrawLine(bbe_px(0), bbe_py(y), bbe_px(BB_PITCH_LEN), bbe_py(y), Fade(BBE_LINE, 0.12f));
    }
    // Halfway line + wide-zone lines (wide zones: y 0-3 and 11-14).
    DrawLineEx((Vector2){(float)bbe_px(13), (float)bbe_py(0)},
               (Vector2){(float)bbe_px(13), (float)bbe_py(BB_PITCH_WID)}, 3, BBE_LINE);
    DrawLineEx((Vector2){(float)bbe_px(0), (float)bbe_py(4)},
               (Vector2){(float)bbe_px(BB_PITCH_LEN), (float)bbe_py(4)}, 2, Fade(BBE_LINE, 0.5f));
    DrawLineEx((Vector2){(float)bbe_px(0), (float)bbe_py(11)},
               (Vector2){(float)bbe_px(BB_PITCH_LEN), (float)bbe_py(11)}, 2, Fade(BBE_LINE, 0.5f));
    // End-zone borders.
    DrawLineEx((Vector2){(float)bbe_px(1), (float)bbe_py(0)},
               (Vector2){(float)bbe_px(1), (float)bbe_py(BB_PITCH_WID)}, 2, Fade(BBE_LINE, 0.7f));
    DrawLineEx((Vector2){(float)bbe_px(BB_PITCH_LEN - 1), (float)bbe_py(0)},
               (Vector2){(float)bbe_px(BB_PITCH_LEN - 1), (float)bbe_py(BB_PITCH_WID)}, 2,
               Fade(BBE_LINE, 0.7f));
}

static void bbe_draw_players(const bb_match* m) {
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location != BB_LOC_ON_PITCH) continue;
        int team = BB_TEAM_OF(s);
        int cx = bbe_px(p->x) + BBE_CELL / 2;
        int cy = bbe_py(p->y) + BBE_CELL / 2;
        Color col = team == BB_HOME ? BBE_HOME : BBE_AWAY;
        bool down = p->stance != BB_STANCE_STANDING;
        bool stunned = p->stance == BB_STANCE_STUNNED || p->stance == BB_STANCE_STUNNED_USED;

        if (down) col = Fade(col, 0.55f);
        DrawCircle(cx, cy, BBE_CELL * 0.38f, col);
        DrawCircleLines(cx, cy, BBE_CELL * 0.38f, Fade(BLACK, 0.6f));
        if (down) {
            // Prone: bar across the token. Stunned: a second crossing bar.
            DrawLineEx((Vector2){(float)(cx - 10), (float)cy}, (Vector2){(float)(cx + 10), (float)cy},
                       3, RAYWHITE);
            if (stunned) {
                DrawLineEx((Vector2){(float)cx, (float)(cy - 10)}, (Vector2){(float)cx, (float)(cy + 10)},
                           3, RAYWHITE);
            }
        }
        // Shirt number (slot within team).
        char num[4];
        snprintf(num, sizeof(num), "%d", BB_SLOT_OF(s) + 1);
        int tw = MeasureText(num, 12);
        DrawText(num, cx - tw / 2, cy - 6, 12, RAYWHITE);
        // Ball carrier ring + ball.
        if (p->flags & BB_PF_HAS_BALL) {
            DrawCircleLines(cx, cy, BBE_CELL * 0.46f, BBE_GOLD);
            DrawCircle(cx + 9, cy - 9, 5, BBE_BALL);
            DrawCircleLines(cx + 9, cy - 9, 5, RAYWHITE);
        }
    }
}

static void bbe_draw_ball(const bb_match* m) {
    if (m->ball.state != BB_BALL_ON_GROUND && m->ball.state != BB_BALL_IN_AIR) return;
    int cx = bbe_px(m->ball.x) + BBE_CELL / 2;
    int cy = bbe_py(m->ball.y) + BBE_CELL / 2;
    if (m->ball.state == BB_BALL_IN_AIR) {
        DrawCircleLines(cx, cy, 7, BBE_GOLD); // in flight: hollow marker
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

    DrawRectangle(0, 0, BBE_WIN_W, BBE_HUD_H + BBE_MARGIN - 4, (Color){24, 26, 30, 255});

    // Score line: HOME name score - score AWAY name, deciding side marked.
    snprintf(buf, sizeof(buf), "%s%s  %d - %d  %s%s",
             m->decision_team == BB_HOME ? "> " : "  ", home,
             m->score[BB_HOME], m->score[BB_AWAY], away,
             m->decision_team == BB_AWAY ? " <" : "  ");
    DrawText(buf, BBE_MARGIN, 10, 22, RAYWHITE);
    DrawCircle(BBE_MARGIN - 8, 21, 5, BBE_HOME);
    DrawCircle(BBE_MARGIN + MeasureText(buf, 22) + 10, 21, 5, BBE_AWAY);

    snprintf(buf, sizeof(buf), "half %d   turn %d/%d   decision %d   %s",
             m->half, m->turn[0], m->turn[1], env->decisions, c->banner);
    DrawText(buf, BBE_MARGIN, 38, 16, (Color){170, 175, 185, 255});
}

static void bbe_render_draw(Bloodbowl* env) {
    if (env->client == NULL) bbe_render_init(env);
    if (WindowShouldClose()) {
        CloseWindow();
        exit(7); // spectate.sh: user closed the window -> stop the loop
    }
    BeginDrawing();
    ClearBackground((Color){24, 26, 30, 255});
    bbe_draw_pitch();
    bbe_draw_ball(&env->match);
    bbe_draw_players(&env->match);
    bbe_draw_hud(env);
    EndDrawing();
}

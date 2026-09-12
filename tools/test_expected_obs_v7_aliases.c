#include <stdio.h>
#include <string.h>
#include "bloodbowl.h"

typedef struct { Bloodbowl e; uint8_t o[2][BBE_OBS_SIZE]; unsigned char m[2][BBE_MASK_SIZE]; } F;
static void init(F *f) {
    memset(f, 0, sizeof *f);
    for (int a=0;a<2;a++) { f->e.obs_ptr[a]=f->o[a]; f->e.action_mask_ptr[a]=f->m[a]; f->e.v4_dirty[a]=1; }
    f->e.match.status=BB_STATUS_DECISION; f->e.match.active_team=0; f->e.match.decision_team=0;
    f->e.match.ball.state=BB_BALL_OFF_PITCH; f->e.match.ball.carrier=BB_NO_PLAYER;
    f->e.match.rerolls[0]=1;
    for (int i=0;i<BB_NUM_PLAYERS;i++) f->e.match.players[i].location=BB_LOC_RESERVES;
    bb_player *p=&f->e.match.players[0]; p->location=BB_LOC_ON_PITCH; p->x=5;p->y=5;p->ma=6;p->st=5;p->ag=4;p->pa=5;p->av=10;
    f->e.match.stack_top=2;
    f->e.match.stack[0]=(bb_frame){.proc=BB_PROC_MOVE,.phase=1,.a=0,.b=BB_ACT_MOVE,.x=6,.y=5};
    f->e.match.stack[1]=(bb_frame){.proc=BB_PROC_TEST,.phase=0,.a=0,.b=BB_TEST_RUSH,.x=2,.data=(uint16_t)(1u<<12)};
    bbe_refresh_legal(&f->e); bbe_fill_mask(&f->e,0);
}
static void emit(F *f){ bbe_emit_all(&f->e); }
static int differs(F *a,F *b){ return memcmp(a->o[0],b->o[0],BBE_OBS_SIZE)!=0; }
int main(void){ F a,b; int failures=0;
    init(&a);init(&b); a.e.match.bonus_rerolls[0]=1; emit(&a);emit(&b);
    if(!differs(&a,&b)){puts("FAIL bonus alias");failures++;}
    init(&a);init(&b);bb_add_skill(&a.e.match.players[0].skills,BB_SK_LONER);bb_add_skill(&b.e.match.players[0].skills,BB_SK_LONER);a.e.match.players[0].p_loner=3;b.e.match.players[0].p_loner=4;emit(&a);emit(&b);
    if(!differs(&a,&b)){puts("FAIL Loner alias");failures++;}
    init(&a);init(&b);bb_add_skill(&a.e.match.players[0].skills,BB_SK_BLOODLUST);bb_add_skill(&b.e.match.players[0].skills,BB_SK_BLOODLUST);a.e.match.players[0].p_bloodlust=2;b.e.match.players[0].p_bloodlust=3;emit(&a);emit(&b);
    if(!differs(&a,&b)){puts("FAIL Bloodlust alias");failures++;}
    puts(failures ? "obs-v7 aliases remain" : "PASS all three obs-v7 aliases resolved"); return failures!=0;
}

# GRAVITY の画面と部品

GRAVITY（Android版 15.2.1）の画面ごとの部品（resource-id）と、画面の移り方をまとめたもの。
ボット（自動返信・タスク・ルーレット）を作るときに、ここを見れば実機を触らずに見当がつくようにする。

- 調べた日: 2026-10-14。MuMuの本体のアカウント（Androidユーザー0）で、押す前に毎回画面を読み直しながら開いた
- 部品の名前は `anonymous.sns.community.gravity:id/` を省いて書く。「-」は resource-id の無い部品
- 画面の大きさは 540x960。ディスプレイ番号は毎回変わる（2 → 4 → 16 → 20 を実測）。`dumpsys activity activities` で探すこと
- 生の画面の記録は `recordings/screens/2026-10-14/`（他の人の名前が入るので、リポジトリには入らない。このPCにだけある）。
  テスト用の画面は `tests/fixtures/`（伏せ字にしたもの）
- ⚠️ 他の人の名前・ID・ルーム名・投稿の本文は、この文書に書かないこと（リポジトリは公開）

## 開けていない画面

本人の決定（2026-10-14）:「人から見て、こちらの動きが分かる画面は、自分のルームとプロフィールだけ」。

| 画面 | 開けていない理由 |
|---|---|
| 他の人のプロフィール | **足あと**が付く（メッセージのタブに「足あと」の一覧がある）。部品は以前に送り先のプロフィールで調べてある（`friend_profile_*.xml`） |
| 他の人の音声ルーム | 入ると「〜が音声ルームに参加しました」と出る |
| 1対1のメッセージの中 | 既読が付きうる。部品は以前に調べてある（`chat.xml`） |
| ショップ・GRAVITY STAR・星粒・守護者・ガチャの中 | お金・ポイントを使う画面。ガチャは開いて読んだだけ（Webの画面） |
| アカウントの切り替え・追加・ログアウト | 押すと元に戻せない |
| 話し相手をみつける・心友ノック などのつながる機能 | 他の人とつながる |

## 全体の地図

```
下のタブ（MainActivity の中で切り替わる。画面のクラスは変わらない）
├─ ホーム        tab_feed     … 新着 / みつける / フォロー（上のタブ）
│   ├─ 検索       btnSearch    → search.SearchActivity
│   ├─ 投稿       cvRoot の中  → feed.view.NewFeedDetailActivity
│   └─ 投稿を作る（右下の＋）   → addfeed.view.AddFeedActivity
├─ コミュニティ  tab_planet   … 惑星の一覧・惑星のイベント・惑星の投稿
├─ 音声ルーム    tabVoiceRoom … ルームの一覧（フォロー / 全て / HOT …）
│   ├─ 検索       ivRoomSearch    → metaverse.voiceroom.VoiceRoomSearchActivity
│   ├─ イベント   ivRoomActivity  → metaverse.voiceroom.VoiceRoomActivityActivity
│   └─ ランキング ivRoomRankList  → metaverse.voiceroom.rank.VoiceRoomRankListActivity
├─ メッセージ    tab_message  … いいね / コメント/＠ / リクエスト / 足あと、すべて / 友達 / グループチャット / 公式アカウント
│   ├─ いいね      clVote   → message.msgbox.MsgBoxVoteActivity
│   ├─ コメント/＠ clComment → message.msgbox.MsgBoxCommentActivityV2
│   ├─ リクエスト  clFriend → message.msgbox.MsgBoxFriendActivity（題は「フォロワー」）
│   ├─ 足あと      clOther  → message.msgbox.FootprintActivity
│   ├─ 通知        ivNotify → discover.SocialMessageActivity
│   ├─ 検索        ivSearch → message.search.DmSearchActivity
│   ├─ 話し相手    ivSocialTools → 下からのシート（MainActivity のまま）
│   ├─ 1対1        → message.view.MessageDetailActivity
│   └─ グループ    → message.view.MsgDetailGroupActivity
└─ マイページ    tab_center
    ├─ ポイント     clPoint      → point.TaskCenterActivity（タスクと同じ画面）
    ├─ パス         clPass       → pass.PassCenterActivity
    ├─ 2階          ivSecondFloor → center.view.CenterSecondFloorActivity
    ├─ メニュー     clDrawer     → 左から出る引き出し（MainActivity のまま）
    │   ├─ バッグ               → center.decoration.DecorationManagerActivity
    │   ├─ アナリティクス       → web.WebViewActivity
    │   ├─ 音声ルームオーナーセンター → web.WebViewActivity
    │   └─ 設定                 → settings.SettingsActivity → BasicSettingActivity / NotificationSettingActivity …
    ├─ 情報編集     tvEditProfile → center.view.profile.ProfileActivity
    ├─ フォロー中・フォロワー・友達 → center.view.profile.RelationshipListActivityV2
    └─ 機能の並び（rvFunction）
        ├─ ガチャ        → metaverse.voiceroom.VoiceRoomLotteryActivity（Web）
        ├─ 質問ボックス  → ask.AskBoxMainActivity
        ├─ タスク        → point.TaskCenterActivity
        ├─ 心理テスト    → heartfriend.HeartFriendDiagnosisActivity
        └─ iUぷらねっと  → pet.PetAdoptActivity

音声ルーム metaverse.voiceroom.VoiceRoomActivity
    ├─ ルーム名     llTitle     → metaverse.voiceroom.VoiceRoomInfoActivity
    ├─ ランキング   vRank       → metaverse.voiceroom.rank.VoiceRoomRankListActivity
    ├─ アナウンス   vNotice     → metaverse.voiceroom.VoiceRoomNoticeActivity
    ├─ ゲスト（N人）tvUserCount → metaverse.voiceroom.VoiceRoomUsersOwnerCtrlActivity
    ├─ …           clMore      → 下からのシート（ルームメニュー）
    ├─ 機能一覧     roomerBtnMenu → 下からのシート（ミニゲーム）
    └─ 小さくする   ivZoomout   → ルームに入る前の画面へ戻る（ホームとは限らない）
```

クラス名は `com.hiclub.android.gravity.` を省いた。

## どの画面にもあるもの

| 部品 | 意味 |
|---|---|
| `nav_view` / `tab_layout` | 下のタブの帯（y=889〜960） |
| `tab_feed` `tab_planet` `tabVoiceRoom` `tab_message` `tab_center` | 下のタブ。文字は `tvFeed` `tvPlant` `tvVoiceRoom` `tvMessage` `tvCenter` |
| `tvRedMessage` / `centerRedPoint` | メッセージの未読数 / マイページの赤い点 |
| `bpvVoiceRoom` | 小さくした音声ルームの丸（[412,650][540,778] あたり。どの画面にも重なる）。⚠️ 押すとルームが開く |
| `shimmerTextView` | **人の名前**はほぼこれ（親が `tvName` / `tv_name` / `tvTitle` / `tvAnchorName` など） |
| `portrait2D` `ivPortrait` `ivPortraitFrame` | アイコンとその枠 |
| 戻るボタン | **画面ごとに名前が違う**: `ivLeft` `btnBack` `rlBack` `iv_back` `ivBack` `back_iv`（`rlBack` の中） |
| `design_bottom_sheet` + `touch_outside` | 下から出るシート。`touch_outside` は画面いっぱいの大きさ |

### 投稿の枠（ホーム・コミュニティ・マイページ・いいねの一覧で同じ形）

```
cvRoot → include → llFeedItem
  feedUserProfile
    iv_profile（アイコン） / tv_name → shimmerTextView（名前） / llTimeWithTag → tv_time（時刻）, tvViewScope（公開範囲）
    llRightContent → btnFollow「フォロー」 / btnChat「メッセージ」 / btnMore（…） / btnClose（×）
  tvDesc → tvContent（本文）, tvFold「もっとみる」
  momentPhotos → image（写真） / feedVideoView（動画）
  includeFeedActionBar
    btnCollect（保存） / tvComment（コメント数） / clLike → ivLike, tvLike（いいね数） / clShare → btn_share
```

- 右上は一覧によって変わる: 新着=`btnFollow`+`btnClose`、フォローのタブ=`btnChat`「メッセージ」+`btnMore`、自分の投稿=`btnMore`だけ
- コミュニティの投稿は上に惑星の帯が付く（`cl_star_top_info` → `tv_star_name`）
- ⚠️ ホームの上のタブの「フォロー」と、投稿の `btnFollow`「フォロー」は同じ文字。文字で探さないこと

## 下のタブ

### ホーム（MainActivity）

| 部品 | 意味 |
|---|---|
| `tabs` の中の文字（resource-id無し） | 新着 / みつける / フォロー。文字に resource-id が無く、押せる印も無い。**位置で押す** |
| `btnSearch` | 検索 → SearchActivity |
| `subTabs` / `btnExpand` | みつける の分類（すべて / 質問・相談 / 人生あるある / 動画 / キャリア …）と、その一覧を広げるボタン |
| `feedNewList` | 投稿の一覧 |
| `rvList` → `ivAvatar` `tvName` `ivVoiceRole` | 一覧の上の、音声ルームにいる人の並び |
| `tvTitle`「今この瞬間、誰かと話したい」 `tvUserCount` `btnJump`「チェック」 | 新着の上の、話し相手を探す案内 |

### コミュニティ（MainActivity）

| 部品 | 意味 |
|---|---|
| `ivStarList` `ivSearch` `ivOfficialActivity` | 惑星の一覧 / 検索 / 公式のイベント |
| `rvStarList` → `clStar` `tvName` `tvNewFeedNum` | 入っている惑星と新着数 |
| `rvStarActivities` → `ivCover` `tvEndTime` `btnJoin`「参加」 | 惑星のイベント。⚠️ 参加は押さない |
| `feedNewList` | 惑星の投稿（投稿の枠の上に惑星の帯） |

### 音声ルームの一覧（MainActivity）

| 部品 | 意味 |
|---|---|
| `tvTabSquare`「音声ルーム」 `ivRoomSearch` `ivRoomActivity` `ivRoomRankList` | 題・検索・イベント・ランキング |
| `tabs` | フォロー / 全て / HOT …（5つ） |
| `srvList` | ルームの一覧。1件は `ivCover`（画像）, `tvAnchorName`→`shimmerTextView`（オーナー）, `tvLabel`（ジャンル）, `tvTag`（#タグ）, `tvUserCount`（人数）, `tvName`（ルーム名）, `ivIsHot` |

⚠️ 一覧のルームを押すと入室する（他の人に「参加しました」と出る）。

### メッセージ（MainActivity）

| 部品 | 意味 |
|---|---|
| `ivSocialTools` `ivSearch` `ivNotify`（`notifyRedDot`=未読数） | 話し相手 / 検索 / 通知 |
| `clVote`「いいね」 `clComment`「コメント/＠」 `clFriend`「リクエスト」 `clOther`「足あと」 | 上の4つ。未読は `tvRedPointVote` など、足あとの増えた数は `footprintAnimView` |
| `tvTabText` | すべて / 友達 / グループチャット / 公式アカウント（押せる印は無い。位置で押す） |
| `friendRv` → `swipe_content` | 会話の一覧。1件は `avatarLayout`, `tvTitle`→`shimmerTextView`（相手かグループの名前）, 時刻（resource-id無し）, `tvContent`（最後の発言）, `flRedPoint`（未読数） |

### マイページ（MainActivity）

| 部品 | 意味 |
|---|---|
| `clPoint`→`tvPoint` / `llToolbarCoin`→`tvBalance` | マイポイント（1000以上は「12.3K」のように丸める。正確な数はタスク画面の `tvPoint`）/ コイン |
| `clPass` `ivSecondFloor` `ivShare` `clDrawer` | パス / 2階 / シェア / メニュー |
| `tvName`→`shimmerTextView` / `tvCustomId`「ID …」 / `tvFamilyBadge` / `tvProfile` | 自分の名前・ID・クランの札・紹介文 |
| `rvInterestTag`→`tvTag` | 興味のタグ |
| `llFollowing` `llFollower` `llFriend`（数は `tvFollowingCount` など） | フォロー中・フォロワー・友達 → RelationshipListActivityV2 |
| `tvEditProfile`「情報編集」 | → ProfileActivity |
| `rvFunction`→`clWebViewContainer`→`ivIcon` `tvTitle` | 機能の並び（ガチャ / 質問ボックス / タスク / 心理テスト / iUぷらねっと）。`countRedPoint` は件数。**押す場所は `clWebViewContainer` か `ivIcon`**（タスクの自動化は `find_function_entry` で探している） |
| `tabs` の中の文字 | 全ての投稿 / アルバム / マイデータ / つながり / コレクト。⚠️ 選ぶと帯が横に送られて位置が変わる。押す前に読み直す |
| 全ての投稿 `rv`→`cvRoot` | 自分の投稿（投稿の枠） |
| アルバム `rv`→`iv_image` | 写真 |
| マイデータ | `clTitleWall`（称号ウォール）, `rvTitle`, ランキング, `llCharmLevel` `llStarLevel` `llVoiceRoomLevel`（各レベル） |
| つながり | `nsBestFriend`→`includeCoupleCard`（`ivMine` `tvMineName`） |

#### メニュー（引き出し。`drawer` [0,0][337,960]）

`llCoin`（コイン）, `cpvPortrait`（アイコン）, `tvName`, `ivSwitchAccount`（⚠️ アカウントの切り替え）, `rlStar`「GRAVITY STAR」, `rlCoin`「GRAVITY 星粒」, `rlDecoration`「バッグ」, `rlAuthor`「アナリティクス」, `rlGuard`「GRAVITY守護者」, `rlGoodAnchorAuthorize`「音声ルームオーナーセンター」, `rlFeedback`, `rlQuestion`「よくある質問」, `rlSetting`「設定」。

⚠️ メニューから開いた画面を戻ると、**メニューは開いたまま**。そこでもう一度 `clDrawer` を押すと閉じる（押した位置がメニューの外のため）。

## メッセージの奥

| 画面 | 主な部品 |
|---|---|
| いいね MsgBoxVoteActivity | `ctbTitle`（`ivLeft` `tvTitle`）, `rvMsgList`。1件は `img_head1`, `tv_title`（名前）, `rcTvRelationShip`「友達」, `tvInfo`「さんがいいね済」「さんがコメントをいいね済」, `tv_date`, `cl_content`→`tv_feed`（どの投稿か）, `rcTvMBTI` |
| コメントと@ MsgBoxCommentActivityV2 | `cl_title`（`iv_back` `tv_title`）, `rvMsgList`。1件は `img_head`, `tv_title`, `tvComment`「さんがコメント済」, `tv_date`, `tv_feed`, `tv_content`（コメントの本文）, `ll_vote`「いいね」, `llComment`「コメント」。⚠️ 一覧の中に、いいね・返信のボタンがある |
| フォロワー MsgBoxFriendActivity | `rvMsgList`。1件は `iv_portrait`, `tvName`, `tvDesc`「さんがあなたをフォロー済」, `tv_time`, `tvStatus`「承認」/「メッセージ」。⚠️ 承認は押さない |
| 足あと FootprintActivity | `tabs`（足あと / あなたの足あと）, `llWeekVisit`（今週の足あと）, `llVisitGtThree`（複数回・互いに）, `tvUserName` `tvCount`, `clSwitch`→`switcher`「訪問者情報を表示する」 |
| 通知 SocialMessageActivity | `tabs`（グループチャットの申請 / 惑星からのお知らせ）, `tvNoData` |
| 検索 DmSearchActivity | `etSearch`「ユーザー / グルチャ / 公式」, `tvCancel` |
| グループチャット MsgDetailGroupActivity | `includeTopBar`（`rlBack`, `headTv`「グループ名(人数)」, `moreRl`）, `friendRv`→`otherMessageView`（`tvTime`, `ivPortrait`, `llBaseInfo`→`shimmerTextView`, `flContainer`→`clBody`）。入力は1対1と同じ `msg_detail_et` `ivSendText`、下に `ivFaceKeyBoard` `clImg` `clVideo` `ivGift` `ivVoiceRoom` |
| 話し相手のシート（MainActivity） | `clBottomBar`, `tvTitle`（話し相手をみつける / 心友ノック / グラじゃんポン …）, `rvContent`→`clContainer`x6, `ivGroupEntrance`, `chatStatusSetting` |

グループチャットの音声ルームの案内は `clBody` の中に `tvStar`（ジャンル）, `tvVoiceRoomTitle`（ルーム名）, `ivIcon`。⚠️ 押すと入室する。

## ホームの奥

| 画面 | 主な部品 |
|---|---|
| 検索 SearchActivity | `etSearch`「投稿/ユーザー/惑星/タグを検索」, `tvCancel`, `rlHistory`（`clearTv`「全て削除」, `rvHistory`）, `tabLayout`（HOTトピック / 悩み＆相談 / グルメ …）, `rvHashtag`→`titleTv`（#タグ）`contentTv`（N人使用中）。⚠️ 開くと入力欄にキーボードが出ていて、**1回目の戻るはキーボードを閉じるだけ** |
| 投稿 NewFeedDetailActivity | 投稿の枠 + `tvCommentScope`, `tvHot`「注目」/`tvNew`「新着」, `feedCommentList`, 入力 `etContent`「すてきなコメントを残そう！」 `btnSend`「送る」, `btnFaceKeyboard` `btnAddMusic` `btnAddPhoto` `btnAtUser`。自分の投稿の `btnMore` は下からのシート（コメント許可対象の設定 / 削除 / 固定する） |

投稿を作る画面（AddFeedActivity）・心のこもった「いいね」の一覧（FeedListActivity）は、タスクの自動化のときに調べた（`compose.xml` `feed_heart_list.xml`）。

## 音声ルームの奥

| 画面 | 主な部品 |
|---|---|
| 検索 VoiceRoomSearchActivity | `etSearch`, `tvCancel`, `tvClearHistory`, `rvHistory`, `rvRecommend`（おすすめ）, `rvHotVoiceRoom`（人気ルーム。`tvRank` `tvScore`「人気度」） |
| イベント VoiceRoomActivityActivity | `rlBack`, `tabs`（ランキング / 開催中 / 開催予約）, `srvList`→`ivCover` `tvCount`「参加者：N人」 `tvTime`「終了まで：…」 |
| ランキング VoiceRoomRankListActivity | `tabs`（人気ユーザー / 人気ルーム / 活躍ルーム …、今日 / 昨日 / グラ殿堂 / 累計）, `llRank1`〜`llRank3`（上位3人）, `rvUserInfo`→`tv_name` `tvScore`（キラキラ値） |

## 音声ルームの中（VoiceRoomActivity。ゲストの画面）

チャット欄の読み方は `parse_chat_rows`（`tests/test_chat_rows.py`）にまとめてある。ここでは画面全体の部品を書く。

| 場所 | 部品 |
|---|---|
| 上の帯 `toolbar` | `llTitle`（`ivLevel`, `tvTitle`=ルーム名, `tvPermission`「友達のみ」など）, `clMore`（…）, `ivZoomout`（小さくする）, `ivExit`（⚠️ 退出） |
| 左上 `llHead` | `vRank`（ランキング）, `vNotice`（アナウンス）, `vTaskView`→`tvTitle`「ミッションへ」`tvDesc2`「未受取の報酬あり」 |
| チャット欄 `rvMessages`（⚠️ 上端は画面で変わる。実測 159 / 248） | 発言 `userMessageView`（`clRoot`, `ivPortrait`（**すばやくダブルタップ**すると、入力のシートが開いて、その人への本物のメンション（青い「@名前」）が入力欄の文の**後ろ**に付く。
1回だけのタップはミニプロフィール（`VoiceRoomPassportActivity`。⚠️ 中にギフト・通報などのボタンがある。戻るで閉じる）。
入力のシートが開いているとダブルタップにならない（1回目でシートが閉じ、2回目がふつうのタップになる）。
⚠️ 2026-10-24 実機: 下の入力欄 `etText` に文を入れると（uiautomator2 の set_text）、入力欄にフォーカスが入って、キーボードと入力のシートが
0.4秒ほどで開く（10/22 は開かなかった）。戻る1回でシートもキーボードも閉じ、入れた文は下の入力欄に残る → 閉じてからダブルタップする。
自分のアカウントの発言のアイコンは、ダブルタップしても1回のタップでも何も起きない（自分にはメンションできない）。
`input -d N tap` は1回20〜35ミリ秒（`/system/bin/input` は `cmd input` を呼ぶだけ）。`tap; sleep 0.05; tap` の始まりの間はおよそ90ミリ秒で、メンションが付く。
⚠️ 画面の部品の上では、本物のメンションもただの文字「@名前 」にしか見えない。メンションのあとに入力欄を書き直すと、ただの文字になる。2026-10-22 実機）, `llName`→`tvName`→`shimmerTextView`, `ivCharmLevel`, `flContainer`→`tvContent`）。お知らせ `tvText`（「〜がマイクをもらいました」など）。ミッションの札 `clContent`（`tvContent`「ルーム個人ミッションを達成しました !」, `ivReward`, `tvCount`「x1000」, `btnNext`「景品GETへ」）。⚠️ 景品GETへ は押さない |
| 右の席 `rvSeats` | 座っている席 `ivAvatar` + `vSideView`（`tvPos`=席番号, `ivMuted`（その席がミュート。斜線のマイクの印）, `ivVolume`（話せる席）, オーナーは `ivAnchorLevelIcon`）。空いた席 `ivAdd` + `tvPosition`。⚠️ ivAdd は押さない（席の申請になる） |
| 右下 | `clCount`→`tvUserCount`「ゲスト（N人）」, `rvViewers`。初回課金の案内 `clFirstRecharge`（`ivFirstRechargeClose`, 「あと5日」） |
| 下の帯 `layoutActions` | `etText`「メッセージを送信」（入力欄。空のときは案内文が文字として入っている。ボットはこれで入力欄を探す）, `roomerBtnLottery`, `roomerBtnGift`→`ivIcon`（⚠️ ギフト）, `roomerBtnMenu`（機能一覧）, 入力のシート（`design_bottom_sheet`: `ivImage`, `ivFaceKeyboard`＝顔の一覧を開く, `etText`, `btnSend`「送る」。
シートが開いている間は、画面の読み取りにシートの部品しか出ない。⚠️ しばらく何もしていないと、入力欄の1回目のタップでシートが開かないことがある）。
顔の一覧の顔は `fl_root`（文字・説明の印は無い）。押すと入力欄に「[にこやか]」のような符号が入り、GRAVITY が顔の絵にして表示する
（符号の一覧は files/agent/gravity_faces.py。71個。⚠️ 入力欄は約145字で止まる）。2026-10-22 実機,
`roomerBtnMicrophone`（⚠️ マイクの申請。席に座っていればマイクの ON/OFF。**ミュートのとき `selected="true"`**、ONのとき・席にいないときは `false`。画面の「🎤 ON / OFF」の文字は絵の一部で、文字としては読めない。2026-10-22 実機。親の `roomerClBtnApplySeat` は変わらない） |

| 押した先 | 主な部品 |
|---|---|
| `llTitle` → VoiceRoomInfoActivity | `tvRoomName`, `rvMember`→`tvName` `tvRole`（オーナー / 管理人）, `clLevel`（`tvLevel` `tvExp`）, `tvPermission`（公開設定）, `clLabel`（ジャンル）, `tvTopic`（話題）, `tvNotice`（アナウンス）, `tvFamily`（クラン） |
| `vNotice` → VoiceRoomNoticeActivity | `tvUser`（「オーナー〜さんはアナウンス…」）, `tvContent`, `ivNoticeImage` |
| `tvUserCount` → VoiceRoomUsersOwnerCtrlActivity | `tabs`（ルーム応援ランキング / 参加メンバー）, `rv`→`ivAvatar` `tvName`→`shimmerTextView`（オーナーは名前の後ろに「[オーナー]」） |
| `vRank` → VoiceRoomRankListActivity | 音声ルームのタブのランキングと同じ画面 |
| `clMore` → シート | ルームメニュー: シェア / フィードバック / 通報 / エフェクトなし / ボイスチェンジ、ルーム詳細: バッグ / クラン（`tvSection1` `rvSection1` `tvSection2` `rvSection2`） |
| `roomerBtnMenu` → シート | 機能一覧: `btnFerriswheel`（グラ観覧車）, `btnSlot`, `btnSpaceShip`, `btnMonster`, `btnRace` など（ミニゲーム） |

⚠️ **小さくする（`ivZoomout`）と、ルームに入る前の画面に戻る**。2026-10-14 は、グループチャットの案内から入っていたので、MsgDetailGroupActivity に戻った。
ホーム画面に戻るとは限らない。タスクのボットは、戻るだけを押してよい画面（`TASK_BACK_ONLY_ACTIVITIES`: グループチャット・ルームの検索・
イベント・ランキング）なら、戻るでホームへ移る。

⚠️ ルームの画面かどうかは `is_voice_room_screen`（クラス名が `VoiceRoomActivity` / `VoiceRoomTypeNActivity`）で見る。
「voiceroom」を含むかで見ると、ルームの検索・ランキング・イベント・ガチャ・ルーム情報もルームとみなしてしまう（どれも `metaverse.voiceroom` の下）。

## マイページの奥・メニューの奥

| 画面 | 主な部品 |
|---|---|
| 情報編集 ProfileActivity | `btnBack`, `btn_submit`「完了」, `flProfile`（アイコン）, `etCustomId`（ID。1回のみ設定可能）, `et_name`, `btnBirth`, `et_desc`。⚠️ 完了は押さない |
| タスク TaskCenterActivity | タスクの自動化で調べた（`task_center_*.xml`）。マイページの `clPoint` からも同じ画面が開く |
| パス PassCenterActivity | 「ロケットパス」, `btnBuyLevel`「レベル購入」（⚠️）, `rv`→`vRewardFree` `vRewardFee1`（報酬）, `tvLevel` |
| 2階 CenterSecondFloorActivity | `clTitleWall`→`btnToTitleWall`「称号ウォール」, `clHandBook`「コレクション」（`progressBar` `tvCurrentProgress` `tvMaxProgress`）, `clBestFriend`「つながり」 |
| 質問ボックス AskBoxMainActivity | `ivLeft` `ivRight`, `rvQuestion`→`tvContent`（質問）, `tvName`, `btnAnswer`「返信」, `ivMore`, `btnCollectQuestions` |
| 心理テスト HeartFriendDiagnosisActivity | `ivBack`, `tvHeartFriend`「心友ノック」, `ivHelp`, `tabs`（すべての診断 / 診断済み）, `srvList`→`ivCover` `tvCount`「参加者：N人」 `tvTitle` |
| iUぷらねっと PetAdoptActivity | `btnStart`「きみとの物語のはじまり」だけ（⚠️ 押すと始まる） |
| ガチャ VoiceRoomLotteryActivity | Webの画面（`webviewContainer` の中は resource-id 無し） |
| バッグ DecorationManagerActivity | `btnBack`, `llMallEntry`「ショップ」, `tabLayout`→`tvTab`（アイコン / フレーム / 吹き出し …）, `rvPortrait`→`tvName` `tvTag`（使用中 / 期限なし）, `btnFilter`, `btnSendOther`「他人に送る」, `btnUse`「使用する」 |
| アナリティクス・オーナーセンター WebViewActivity | Webの画面（`commonWebView` の中は resource-id 無し） |
| 設定 SettingsActivity | `btnAccountSecurity` `btnNotification` `btnBlack`（ブロック） `btnBasic` `btnAbout` `btnLanguage`, `btnAddAccount` `btnLogout`（⚠️） |
| 基本設定 BasicSettingActivity | `btnVideoAutoPlay` `btnDarkMode` `btnImCloud` `btnFootPrint` `btnFootPrintEnter` `btnVip` `btnGuardList` `btnUserCenterId` `btnLotteryRank` `btnTopicMatch` `btnActivityWindow` `btnStarExposure` `btnChatBlurPornImage` |
| 通知の設定 NotificationSettingActivity | `rlHideFollow` `rlHideComment` `rlHideFeedCount` `rlHideCommentFabulous` `rlFollowingAddFeed` `rlHideFaq` `rlHidePushPlatform` `rlHideVoiceRoom` `rlHideVoiceRoomPush` `rlHideTopicMatch` `rlPointTaskSignInReminder`（それぞれの中に `switcher`） |

## ボットを作るときの注意（今回わかったこと）

- **Webの画面には resource-id が無い**（ガチャ・アナリティクス・オーナーセンター・ルーレット）。文字で探すしかない
- **タブの文字の多くは resource-id も押せる印も無い**（ホームの上のタブ、メッセージの `tvTabText`、マイページのタブ）。位置で押し、押した後は読み直す（帯が横に送られて位置が変わる）
- **同じ文字の別の部品がある**: ホームの上のタブ「フォロー」と `btnFollow`、メッセージの「いいね」（通知の一覧）と投稿の `clLike`。文字だけで探さず、resource-id か位置で絞る
- **下からのシートの `touch_outside` は画面いっぱい**。「押した位置にある部品」で守りを判断すると、シートの中の文言まで拾う。閉じるときは、シートが開いていることを確かめてから戻るを押す
- **戻るの効き方が画面で違う**: 検索の画面は1回目でキーボードを閉じるだけ。メニューから開いた画面を戻るとメニューは開いたまま
- **人の名前は `shimmerTextView`**。名前で探す処理はこれを見る
- **足あと**がある。他の人のプロフィールを開く処理は、本人に見える跡を残す

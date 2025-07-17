import discord
from discord import app_commands
from discord.ext import tasks
import os
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, time, timedelta, timezone
import re

# -------------------- 初期設定 --------------------

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

RANKING_CHANNEL_ID = 1389121886319018086

# 日本時間のタイムゾーン
JST = timezone(timedelta(hours=+9), 'JST')

intents = discord.Intents.default()
intents.reactions = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Google Sheets API認証
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
gc = gspread.authorize(creds)
spreadsheet = gc.open("活動記録") 

log_worksheet = spreadsheet.worksheet("集計")
schedule_worksheet = spreadsheet.worksheet("活動予定")
group_log_worksheet = spreadsheet.worksheet("グループ作業") 
user_settings_worksheet = spreadsheet.worksheet("設定")

TIME_REACTION_MAP = {
    '<:0_5h:1389470335774228591>': 30,   # 0.5時間
    '<:1_0h:1389470330481016913>': 60,   # 1時間
    '<:1_5h:1389470517555236985>': 90,   # 1.5時間
    '<:2_0h:1389470326047375490>': 120,  # 2時間
    '<:2_5h:1389470324168593449>': 150,  # 2.5時間
    '<:3_0h:1389470321064808488>': 180,  # 3時間
    '<:3_5h:1389470316547407903>': 210,   # 3.5時間
    '<:4_0h:1389470436047327323>': 240,   # 4時間
    '<:4_5h:1389470311950319769>': 270,   # 4.5時間
    '<:5_0h:1389470310184783893>': 300,  # 5時間
    '<:5_5h:1389470308309667901>': 330,  # 5.5時間
    '<:6_0h:1389470305725976616>': 360,  # 6時間
    '<:6_5h:1389470303226171412>': 390,   # 6.5時間
    '<:7_0h:1389470301326282752>': 420,   # 7時間
    '<:7_5h:1389470299228999730>': 450,   # 7.5時間
    '<:8_0h:1389470290849038378>': 480,  # 8時間
    '<:8_5h:1389470288898429018>': 510,  # 8.5時間
    '<:9_0h:1389470286046302300>': 540,  # 9時間
    '<:9_5h:1389470283194306580>': 570,   # 9.5時間
    '<:10_0h:1389470280853880934>': 600,   # 10時間
    '<:10_5h:1389470278660395071>': 630,   # 10.5時間
    '<:11_0h:1389470277305372752>': 660,  # 11時間
    '<:11_5h:1389470275162083410>': 690,  # 11.5時間
    '<:12_0h:1389470273018921053>': 720,  # 12時間
    '<:12_5h:1389470271869685803>': 750,   # 12.5時間
    '<:13_0h:1389470269822992434>': 780,   # 13時間
}
# グループ参加用の絵文字
GROUP_REACTION_EMOJI = '✋'

# -------------------- ヘルパー関数 --------------------

def parse_time_to_minutes(time_str: str) -> int:
    hours = 0
    minutes = 0
    hour_match = re.search(r'(\d+(?:\.\d+)?)h', time_str, re.IGNORECASE)
    if hour_match:
        hours = float(hour_match.group(1))
    minute_match = re.search(r'(\d+)m', time_str, re.IGNORECASE)
    if minute_match:
        minutes = int(minute_match.group(1))
    return int(hours * 60 + minutes)

# -------------------- Botのイベントハンドラ --------------------

"""
@client.event
async def on_ready():
    print(f'{client.user} としてログインしました')
    await tree.sync()
    # 定期タスクを開始
    post_weekly_ranking.start()
    post_monthly_ranking.start()
"""

@client.event
async def on_ready():
    print(f'{client.user} としてログインしました')
    await tree.sync()
    post_weekly_total.start()
    post_monthly_total.start()

# -------------------- ランキング集計ロジック  --------------------

async def generate_ranking_embed(period: str, top_n: int = 5, invoker_name: str | None = None):
    """
    指定された期間のランキングEmbedを生成する
    period: 'weekly', 'monthly', 'all_time' のいずれか
    top_n: 上位何位まで表示するか
    invoker_name: コマンド実行者の名前。指定するとその人の順位も表示する
    """
    now = datetime.now(JST)
    
    if period == 'weekly':
        today = now.date()
        start_of_week = today - timedelta(days=today.weekday())
        title = f"🏆 ウィークリー作業時間ランキング ({start_of_week.strftime('%m/%d')}～)"
    elif period == 'monthly':
        title = f"👑 マンスリー作業時間ランキング ({now.strftime('%Y年%m月')})"
        target_date_str = now.strftime('%Y/%m')
    elif period == 'all_time':
        title = "累計作業時間ランキング"
    else:
        return None

    try:
        records = log_worksheet.get_all_records()
    except Exception as e:
        print(f"スプレッドシートの読み取りエラー: {e}")
        return discord.Embed(title="エラー", description="スプレッドシートのデータを取得できませんでした。", color=discord.Color.red())

    ranking = {}
    for record in records:
        try:
            log_date_str = record.get('日付', '')
            if not log_date_str: continue

            # 期間でフィルタリング
            if period == 'weekly':
                log_date = datetime.strptime(log_date_str, '%Y/%m/%d').date()
                if not (start_of_week <= log_date <= today):
                    continue
            elif period == 'monthly':
                if not log_date_str.startswith(target_date_str):
                    continue
            # 'all_time'の場合はフィルタリングしない

            user = record.get('名前')
            time_str = str(record.get('時間', '0')).replace('分', '')
            time_in_minutes = int(time_str) if time_str.isdigit() else 0
            
            if user:
                ranking[user] = ranking.get(user, 0) + time_in_minutes
        except (ValueError, TypeError):
            continue

    if not ranking:
        return discord.Embed(title=title, description="まだ作業記録がありません。", color=discord.Color.blue())

    sorted_ranking = sorted(ranking.items(), key=lambda item: item[1], reverse=True)
    
    embed = discord.Embed(title=title, color=discord.Color.gold())
    
    # 上位N人のランキングを表示
    description_lines = []
    for i, (user, total_minutes) in enumerate(sorted_ranking[:top_n]):
        hours = total_minutes // 60
        minutes = total_minutes % 60
        time_display = f"{hours}時間{minutes}分" if hours > 0 else f"{minutes}分"
        description_lines.append(f"**{i+1}位**: {user} - `{time_display}`")
    
    embed.description = "\n".join(description_lines)

    # コマンド実行者の順位を表示
    if invoker_name:
        invoker_rank = -1
        invoker_time = 0
        for i, (user, total_minutes) in enumerate(sorted_ranking):
            if user == invoker_name:
                invoker_rank = i + 1
                invoker_time = total_minutes
                break
        
        if invoker_rank != -1:
            hours = invoker_time // 60
            minutes = invoker_time % 60
            time_display = f"{hours}時間{minutes}分" if hours > 0 else f"{minutes}分"
            embed.add_field(
                name="あなたの順位",
                value=f"あなたは **{invoker_rank}位** です！ (合計: `{time_display}`)",
                inline=False
            )
        else:
             embed.add_field(
                name="あなたの順位",
                value="あなたはまだランクインしていません。",
                inline=False
            )
        
    return embed

async def calculate_total_hours(period: str):
    """指定された期間の合計作業時間（分）を計算する"""
    now = datetime.now(JST)
    total_minutes = 0

    if period == 'weekly':
        today = now.date()
        start_of_week = today - timedelta(days=today.weekday())
    elif period == 'monthly':
        target_date_str = now.strftime('%Y/%m')
    
    try:
        records = log_worksheet.get_all_records()
    except Exception as e:
        print(f"スプレッドシートの読み取りエラー: {e}")
        return -1 # エラーを示す値を返す

    for record in records:
        try:
            log_date_str = record.get('日付', '')
            if not log_date_str: continue

            # 期間でフィルタリング
            if period == 'weekly':
                log_date = datetime.strptime(log_date_str, '%Y/%m/%d').date()
                if not (start_of_week <= log_date <= today):
                    continue
            elif period == 'monthly':
                if not log_date_str.startswith(target_date_str):
                    continue
            # 'all_time'の場合はフィルタリングしない

            time_str = str(record.get('時間', '0')).replace('分', '')
            total_minutes += int(time_str) if time_str.isdigit() else 0
        except (ValueError, TypeError):
            continue
            
    return total_minutes

# -------------------- スラッシュコマンドの実装 --------------------

@tree.command(name="total_hours", description="チーム全体の合計作業時間を表示します。")
@app_commands.describe(period="表示する期間を選択してください")
@app_commands.choices(period=[
    app_commands.Choice(name="今週", value="weekly"),
    app_commands.Choice(name="今月", value="monthly"),
    app_commands.Choice(name="累計", value="all_time"),
])
async def total_hours(interaction: discord.Interaction, period: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    
    total_minutes = await calculate_total_hours(period.value)

    if total_minutes < 0:
        await interaction.followup.send("エラーが発生し、時間を集計できませんでした。", ephemeral=True)
        return

    hours = total_minutes // 60
    minutes = total_minutes % 60
    time_display = f"{hours}時間{minutes}分"

    period_name_map = {
        'weekly': '今週',
        'monthly': '今月',
        'all_time': '累計'
    }
    period_name = period_name_map.get(period.value)

    embed = discord.Embed(
        title=f"🕒 {period_name}の合計作業時間",
        description=f"チーム全体の合計作業時間は **{time_display}** です！",
        color=discord.Color.teal()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

"""
# 機能1: /rank コマンド 
@tree.command(name="rank", description="作業時間のランキングを表示します。")
@app_commands.describe(
    period="表示する期間を選択してください",
    top_n="表示する上位人数（デフォルトは5人）"
)
@app_commands.choices(period=[
    app_commands.Choice(name="ウィークリー", value="weekly"),
    app_commands.Choice(name="マンスリー", value="monthly"),
    app_commands.Choice(name="累計", value="all_time"), # 「累計」を追加
])
async def rank(interaction: discord.Interaction, period: app_commands.Choice[str], top_n: int = 5):
    # ephemeral=True で、コマンド実行者にしか見えないようにする
    await interaction.response.defer(ephemeral=True) 
    
    embed = await generate_ranking_embed(
        period=period.value, 
        top_n=top_n, 
        invoker_name=interaction.user.display_name # 実行者の名前を渡す
    )
    
    if embed:
        # ephemeral=True をここにも指定
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send("エラーが発生しました。", ephemeral=True)

"""

# 機能2: /notify コマンド 
@tree.command(name="notify", description="作業記録完了時のDM通知をON/OFFします。")
async def notify(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    try:
        # ユーザーの設定を探す
        cell = user_settings_worksheet.find(user_id, in_column=1)
        
        if cell:
            # 設定が見つかった場合、ON/OFFを切り替える
            current_status_str = user_settings_worksheet.cell(cell.row, 2).value
            new_status = not (current_status_str == 'TRUE')
            user_settings_worksheet.update_cell(cell.row, 2, str(new_status).upper())
            status_text = "ON" if new_status else "OFF"
            await interaction.response.send_message(f"✅ DM通知を **{status_text}** にしました。", ephemeral=True)
        else:
            # 設定が見つからない場合、新しく作成してONにする
            user_settings_worksheet.append_row([user_id, 'TRUE'])
            await interaction.response.send_message("✅ DM通知を **ON** にしました。", ephemeral=True)

    except Exception as e:
        await interaction.response.send_message("エラーが発生しました。設定を変更できませんでした。", ephemeral=True)
        print(f"通知設定エラー: {e}")

# 機能3: /schedule コマンド
@tree.command(name="schedule", description="作業予定をチャンネルに投稿します。")
@app_commands.describe(task="予定されている作業内容", date="作業日 (例: 2025/07/15)")
async def schedule(interaction: discord.Interaction, task: str, date: str):
    await interaction.response.defer()
    embed = discord.Embed(
        title="🗓️ 作業予定のお知らせ",
        description=f"**作業内容:** {task}\n**日付:** {date}",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="作業時間の記録方法",
        value="作業が終わったら、時間絵文字でリアクションしてください！"
    )
    schedule_message = await interaction.followup.send(embed=embed, wait=True)
    schedule_worksheet.append_row([str(schedule_message.id), task, date])
    

# 機能4: /log コマンド
@tree.command(name="log", description="その場の作業を記録し、参加者を募ります。")
@app_commands.describe(task="作業内容", time="作業時間 (例: 2h, 30m)", note="メモ (任意)")
async def log(interaction: discord.Interaction, task: str, time: str, note: str = ""):
    await interaction.response.defer()
    try:
        time_in_minutes = parse_time_to_minutes(time)
        if time_in_minutes <= 0:
            await interaction.followup.send("時間は正しく入力してください。", ephemeral=True)
            return
    except Exception:
        await interaction.followup.send("時間の形式が不正です。", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📝 作業記録: {task}",
        description=f"同じ作業をした人は {GROUP_REACTION_EMOJI} または時間絵文字でリアクションしてください！",
        color=discord.Color.green()
    )
    embed.add_field(name="報告者", value=interaction.user.display_name, inline=True)
    embed.add_field(name="時間（一人あたり）", value=time, inline=True)
    
    log_message = await interaction.followup.send(embed=embed, wait=True)
    
    author_name = interaction.user.display_name

    # GroupLogsシートにこの作業を登録
    group_log_worksheet.append_row([str(log_message.id), task, time_in_minutes, author_name])
    
    # 最初の報告者の記録をログシートに追加
    log_row = [
        interaction.user.display_name,
        datetime.now().strftime('%Y/%m/%d'),
        task,
        f"{time_in_minutes}分",
        note,
        datetime.now().isoformat(),
        str(log_message.id)
    ]
    log_worksheet.append_row(log_row)

    # ユーザーのDM設定を確認
    should_send_dm = False
    try:
        cell = user_settings_worksheet.find(str(interaction.user.id), in_column=1)
        if cell and user_settings_worksheet.cell(cell.row, 2).value == 'TRUE':
            should_send_dm = True
    except gspread.exceptions.CellNotFound:
        pass # 設定がなければDMは送らない
    except Exception as e:
        print(f"DM設定の確認中にエラー: {e}")

    # DM設定がONの場合のみ通知する
    if should_send_dm:
        try:
            time_display = f"{time_in_minutes}分"
            await interaction.user.send(f"✅ 作業記録を受け付けました！\n**作業内容:** {task}\n**記録時間:** {time_display}")
        except discord.Forbidden:
            print(f"{author_name}さんへのDM送信に失敗しました。(DMがブロックされている可能性があります)")

    

# -------------------- リアクションイベントの処理 --------------------

@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # Bot自身のリアクションや、ユーザー情報が取得できない場合は無視
    if payload.user_id == client.user.id: return
    user = await client.fetch_user(payload.user_id)
    if not user or user.bot: return

    # サーバー(Guild)の情報を取得
    guild = client.get_guild(payload.guild_id)
    if not guild: return
    
    # サーバーからメンバー情報を取得
    try:
        member = await guild.fetch_member(payload.user_id)
    except discord.NotFound:
        return # サーバーにいないユーザーなら無視
    
    if not member or member.bot: return
    
    # ★★★ 常にサーバーでの表示名(ニックネーム)を取得する ★★★
    user_name = member.display_name 

    emoji = str(payload.emoji)
    message_id = str(payload.message_id)
    should_send_dm = False # DMを送るかどうかのフラグ

    # ユーザーのDM設定を確認
    try:
        cell = user_settings_worksheet.find(str(user.id), in_column=1)
        if cell and user_settings_worksheet.cell(cell.row, 2).value == 'TRUE':
            should_send_dm = True
    except gspread.exceptions.CellNotFound:
        pass # 設定がなければ何もしない (DMなし)
    except Exception as e:
        print(f"DM設定の確認中にエラー: {e}")

    # --- パターン1: /schedule のメッセージへのリアクション ---
    try:
        schedule_cell = schedule_worksheet.find(message_id, in_column=1)
        # スケジュールが見つかり、かつ、時間の絵文字なら記録
        if schedule_cell and emoji in TIME_REACTION_MAP:
            schedule_data = schedule_worksheet.row_values(schedule_cell.row)
            task_name, task_date = schedule_data[1], schedule_data[2]
            time_in_minutes = TIME_REACTION_MAP[emoji]
            
            log_row = [user_name, task_date, task_name, f"{time_in_minutes}分", "", datetime.now().isoformat(), message_id]
            log_worksheet.append_row(log_row)
            
            # DM設定がONの場合のみ送信
            if should_send_dm:
                await user.send(f"✅ 予定作業への参加を記録しました！\n**作業内容:** {task_name}\n**記録時間:** {time_in_minutes}分")

            print(f"スケジュール記録: {user_name} - {task_name} ({time_in_minutes}分)")
            return # 処理完了
    except gspread.exceptions.CellNotFound:
        pass # 見つからなければ次のパターンへ
    except Exception as e:
        print(f"スケジュールリアクション処理中にエラー: {e}")

    # --- パターン2: /log のメッセージへのリアクション ---
    try:
        group_log_cell = group_log_worksheet.find(message_id, in_column=1)
        if group_log_cell:
            group_log_data = group_log_worksheet.row_values(group_log_cell.row)
            task_name = group_log_data[1]
            
            # ケースA: ✋ (参加)リアクションの場合
            if emoji == GROUP_REACTION_EMOJI:
                original_time_in_minutes = int(group_log_data[2])
                
                log_row = [user_name, datetime.now().strftime('%Y/%m/%d'), task_name, f"{original_time_in_minutes}分", "(参加)", datetime.now().isoformat(), message_id]
                log_worksheet.append_row(log_row)

                # DM設定がONの場合のみ送信
                if should_send_dm:
                    await user.send(f"✅ グループ作業への参加を記録しました！\n**作業内容:** {task_name}\n**記録時間:** {original_time_in_minutes}分")
                
                print(f"グループ参加: {user_name} - {task_name} ({original_time_in_minutes}分)")
                return # 処理完了

            # ケースB: 時間の絵文字リアクションの場合
            elif emoji in TIME_REACTION_MAP:
                new_time_in_minutes = TIME_REACTION_MAP[emoji]
                
                log_row = [user_name, datetime.now().strftime('%Y/%m/%d'), task_name, f"{new_time_in_minutes}分", "(別時間で参加)", datetime.now().isoformat(), message_id]
                log_worksheet.append_row(log_row)

                # DM設定がONの場合のみ送信
                if should_send_dm:
                   await user.send(f"✅ グループ作業への参加を記録しました！\n**作業内容:** {task_name}\n**記録時間:** {new_time_in_minutes}分")

                print(f"グループ別時間参加: {user_name} - {task_name} ({new_time_in_minutes}分)")
                return # 処理完了
                
    except gspread.exceptions.CellNotFound:
        pass # 見つからなければ何もしない
    except Exception as e:
        print(f"グループリアクション処理中にエラー: {e}")


@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """リアクションが取り消された際に、その人の作業記録を削除する"""
    if payload.user_id == client.user.id: return

    try:
        # サーバーとメンバーの情報を取得
        guild = client.get_guild(payload.guild_id)
        if not guild: return
        member = await guild.fetch_member(payload.user_id)
        if not member or member.bot: return
        
        user_name = member.display_name
        message_id = str(payload.message_id)

        print("--- リアクション取消イベント検知 ---")
        print(f"探している人: {user_name}")
        print(f"探しているMessage ID: {message_id}")

        # 作業記録シートから、該当する記録を探す
        all_logs = log_worksheet.get_all_records()
        row_to_delete = -1

        for i, log in enumerate(reversed(all_logs)):
            # Message IDと名前が一致する記録を探す
            if (log.get('Message ID') == message_id and log.get('名前') == user_name):
                row_to_delete = len(all_logs) - i
                break
        
        # 対象の行が見つかったら削除
        if row_to_delete != -1:
            log_worksheet.delete_rows(row_to_delete)
            print(f"リアクション取消: {user_name}さんの記録 (Message ID: {message_id}) を削除しました。")

    except Exception as e:
        print(f"リアクション取消処理中にエラー: {e}")

# -------------------- メッセージ削除イベントの処理  --------------------

@client.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    """
    Discordでメッセージが削除された際に、関連するデータを削除する
    """
    message_id = str(payload.message_id)
    
    # --- /log メッセージの削除処理 ---
    try:
        # GroupLogsシートから、削除されたメッセージの情報を探す
        group_log_cell = group_log_worksheet.find(message_id, in_column=1)
        if group_log_cell:
            # 作業記録シート(シート1)から、関連するログを全て削除
            all_log_cells = log_worksheet.findall(message_id, in_column=7) # G列(Message ID)を検索
            # 見つかった行を逆順に削除 (行がずれるのを防ぐため)
            for cell in reversed(all_log_cells):
                log_worksheet.delete_rows(cell.row)
            
            print(f"/logメッセージ削除: Message ID {message_id} に関連する全ての記録を削除しました。")

            # GroupLogsシートからも管理用の行を削除
            group_log_worksheet.delete_rows(group_log_cell.row)
            return
            
    except gspread.exceptions.CellNotFound:
        pass # GroupLogsになければ次へ
    except Exception as e:
        print(f"/logの削除処理中にエラー: {e}")

    # --- /schedule メッセージの削除処理 ---
    try:
        schedule_cell = schedule_worksheet.find(message_id, in_column=1)
        if schedule_cell:
            schedule_worksheet.delete_rows(schedule_cell.row)
            print(f"スケジュールメッセージ削除: Message ID {message_id} の行をSchedulesシートから削除しました。")
            return
    except gspread.exceptions.CellNotFound:
        pass
    except Exception as e:
        print(f"Schedulesシートの行削除中にエラー: {e}")

# -------------------- 定期実行タスク  --------------------

""""
# 最後にタスクを実行した日付を記録しておく変数
last_weekly_run = None
last_monthly_run = None

# 1分ごとにループを回し、時刻をチェックする方法に変更
@tasks.loop(minutes=1)
async def post_weekly_ranking():
    global last_weekly_run
    now = datetime.now(JST)
    
    # 日曜日の22時ちょうど、かつ、今日まだ実行していなければ実行
    if now.weekday() == 6 and now.hour == 22 and (last_weekly_run is None or last_weekly_run.date() != now.date()):
        channel = client.get_channel(RANKING_CHANNEL_ID)
        if channel:
            print("ウィークリーランキングを投稿します...")
            
            # top_n=5 を指定し、invoker_nameは渡さない
            embed = await generate_ranking_embed(period='weekly', top_n=5)
            if embed:
                await channel.send(embed=embed)

            last_weekly_run = now # 実行した日時を記録

# 1分ごとにループを回し、月末かどうかをチェック
@tasks.loop(minutes=1)
async def post_monthly_ranking():
    global last_monthly_run
    now = datetime.now(JST)
    
    # 翌日が次の月なら、今日が月末
    is_last_day = (now + timedelta(days=1)).month != now.month
    
    # 月末の22時30分、かつ、今日まだ実行していなければ実行
    if is_last_day and now.hour == 22 and now.minute == 30 and (last_monthly_run is None or last_monthly_run.date() != now.date()):
        channel = client.get_channel(RANKING_CHANNEL_ID)
        if channel:
            print("マンスリーランキングを投稿します...")

            # top_n=5 を指定し、invoker_nameは渡さない
            embed = await generate_ranking_embed(period='monthly', top_n=5)
            if embed:
                await channel.send(embed=embed)
            
            last_monthly_run = now # 実行した日時を記録

"""

# 毎週日曜日の22時に週間の合計時間を投稿
@tasks.loop(minutes=1)
async def post_weekly_total():
    global last_weekly_run
    now = datetime.now(JST)
    
    if now.weekday() == 6 and now.hour == 22 and (last_weekly_run is None or last_weekly_run.date() != now.date()):
        channel = client.get_channel(RANKING_CHANNEL_ID)
        if channel:
            total_minutes = await calculate_total_hours('weekly')
            if total_minutes >= 0:
                hours = total_minutes // 60
                minutes = total_minutes % 60
                time_display = f"{hours}時間{minutes}分"
                embed = discord.Embed(
                    title="週間の合計作業時間",
                    description=f"今週のチーム合計作業時間は **{time_display}** でした！お疲れ様でした！",
                    color=discord.Color.green()
                )
                await channel.send(embed=embed)
            last_weekly_run = now

# 毎月最終日の22時半に月間の合計時間を投稿
@tasks.loop(minutes=1)
async def post_monthly_total():
    global last_monthly_run
    now = datetime.now(JST)
    is_last_day = (now + timedelta(days=1)).month != now.month
    
    if is_last_day and now.hour == 22 and now.minute == 30 and (last_monthly_run is None or last_monthly_run.date() != now.date()):
        channel = client.get_channel(RANKING_CHANNEL_ID)
        if channel:
            total_minutes = await calculate_total_hours('monthly')
            if total_minutes >= 0:
                hours = total_minutes // 60
                minutes = total_minutes % 60
                time_display = f"{hours}時間{minutes}分"
                embed = discord.Embed(
                    title="月間の合計作業時間",
                    description=f"今月のチーム合計作業時間は **{time_display}** でした！来月も頑張りましょう！",
                    color=discord.Color.gold()
                )
                await channel.send(embed=embed)
            last_monthly_run = now

# -------------------- Botの実行 --------------------
if __name__ == '__main__':
    client.run(TOKEN)
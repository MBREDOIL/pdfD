import os
import re
import sys
import asyncio
import aiohttp
import aiofiles
from os import environ
from pyromod import listen
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.types.messages_and_media import message
from pyrogram.errors import FloodWait
from aiohttp import web

# Get environment variables
API_ID = int(os.getenv("API_ID", "22182189"))
API_HASH = os.getenv("API_HASH", "5e7c4088f8e23d0ab61e29ae11960bf5")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not BOT_TOKEN:
    print("BOT_TOKEN environment variable is not set!")
    sys.exit(1)

# Initialize bot
bot = Client(
    "pdf_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# User task tracker
user_tasks = {}
ADMIN_ID = 6556141430  # Replace with your admin ID

async def download_pdf(url, filename):
    """Download PDF with timeout and retries"""
    for _ in range(2):  # Retry twice
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        async with aiofiles.open(filename, 'wb') as f:
                            await f.write(await response.read())
                        return True
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
    return False

@bot.on_message(filters.command(["start"]))
async def start_handler(_, m: Message):
    await m.reply_text(
        "📚 **PDF Download Bot**\n\n"
        "Send /upload to start uploading PDFs\n"
        "Send /stop to cancel your current task\n"
        "Send /stopall to cancel all tasks (admin)\n\n"
        "Made with ❤️ by @UIHASH"
    )

@bot.on_message(filters.command(["stop"]))
async def stop_handler(_, m: Message):
    chat_id = m.chat.id
    if chat_id in user_tasks:
        user_tasks[chat_id].cancel()
        del user_tasks[chat_id]
        await m.reply_text("🛑 **Your task has been stopped!**")
    else:
        await m.reply_text("⚠️ **No active task to stop!**")

@bot.on_message(filters.command(["stopall"]))
async def stopall_handler(_, m: Message):
    if m.from_user and m.from_user.id != ADMIN_ID:
        await m.reply_text("⛔ **Admin only command!**")
        return
        
    count = 0
    for chat_id, task in list(user_tasks.items()):
        task.cancel()
        del user_tasks[chat_id]
        count += 1
        
    await m.reply_text(f"🛑 **Stopped {count} tasks!**")

@bot.on_message(filters.command(["upload"]))
async def upload_handler(bot: Client, m: Message):
    chat_id = m.chat.id
    if chat_id in user_tasks:
        await m.reply_text("⚠️ **You already have an active task! Use /stop first.**")
        return
        
    # Step 1: Get the text file
    msg = await m.reply_text("📤 **Send me the text file containing PDF links**")
    input_msg = await bot.listen(chat_id, timeout=120)
    if not input_msg.document or not input_msg.document.file_name.endswith('.txt'):
        await msg.edit("❌ **Invalid file! Please send a TXT file.**")
        return
        
    file_path = await input_msg.download()
    await input_msg.delete()
    
    # Read and parse the file
    try:
        with open(file_path, "r") as f:
            content = f.read().splitlines()
        os.remove(file_path)
        
        links = []
        for line in content:
            if not line.strip():
                continue
            parts = line.split(" ||| ")
            if len(parts) >= 4:
                links.append({
                    "college": parts[0].strip(),
                    "course": parts[1].strip(),
                    "batch": parts[2].strip(),
                    "url": parts[3].strip()
                })
        
        if not links:
            await msg.edit("❌ **No valid links found in file!**")
            return
    except Exception as e:
        await msg.edit(f"❌ **Error reading file:** {str(e)}")
        return
        
    # Step 2: Get download range
    await msg.edit(f"📊 **Total {len(links)} links found**\n\nSend range to download (e.g. '1-10' or '5' for single file):")
    input_range = await bot.listen(chat_id, timeout=120)
    try:
        if '-' in input_range.text:
            start, end = map(int, input_range.text.split('-'))
            start = max(1, start)
            end = min(len(links), end)
        else:
            start = end = int(input_range.text)
            start = max(1, start)
            end = min(len(links), end)
        
        if start > end:
            start, end = end, start
            
        links = links[start-1:end]  # Adjust for 0-based index
    except:
        await msg.edit("❌ **Invalid range! Using all files.**")
    await input_range.delete()
        
    # Step 3: Get caption
    await msg.edit("📝 **Enter caption for files**")
    input_caption = await bot.listen(chat_id, timeout=120)
    raw_text3 = input_caption.text
    await input_caption.delete()
    
    # Special caption handling
    highlighter = "️ ⁪⁬⁮⁮⁮"
    MR = highlighter if raw_text3 == 'Robin' else raw_text3
    
    # Step 4: Get thumbnail
    await msg.edit("🖼️ **Send thumbnail photo (type 'no' for no thumbnail)**")
    
    try:
        input_thumb = await bot.listen(chat_id, timeout=120)
        thumb = None
        if input_thumb.photo:
            thumb = await input_thumb.download()
        elif input_thumb.text and input_thumb.text.lower() != 'no':
            await msg.edit("❌ **Invalid input! Using default thumbnail.**")
        await input_thumb.delete()
    except asyncio.TimeoutError:
        await msg.edit("⏱️ **Thumbnail input timed out! Using default thumbnail.**")
        thumb = None
    
    # Start processing
    await msg.edit(f"⏳ **Starting download of {len(links)} files...**")
    
    # Create and track task
    task = asyncio.create_task(process_links(
        bot, m, links, MR, thumb, chat_id
    ))
    user_tasks[chat_id] = task
    task.add_done_callback(lambda t: user_tasks.pop(chat_id, None))

async def process_links(bot, m, links, MR, thumb, chat_id):
    """Process all links for a chat"""
    success = 0
    errors = []
    total = len(links)
    path = f"./downloads/{chat_id}"
    os.makedirs(path, exist_ok=True)
    
    try:
        for idx, link_data in enumerate(links, 1):
            # Check if task was cancelled
            if chat_id not in user_tasks:
                break
                
            college = link_data["college"]
            course = link_data["course"]
            batch = link_data["batch"]
            url = link_data["url"]
            
            # Create caption
            #cc1 = f'{str(file_counter).zfill(3)}. **{college}**\n\n`{course}`\n\n__{batch}__\n\n**Downloaded BY {MR}**'
            cc1 = f'**{idx}. {college}**\n\n`{course}`\n\n__{batch}__'
            
            # Clean filename
            name = f"{idx}_{college}_{course}_{batch}"[:60]
            name = re.sub(r'[^\w\s-]', '', name)
            filename = os.path.join(path, f"{name}.pdf")
            
            # Download PDF
            status = await download_pdf(url, filename)
            if not status:
                errors.append(f"❌ Failed: {college}")
                continue
                
            # Upload file
            try:
                await bot.send_document(
                    chat_id=chat_id,
                    document=filename,
                    caption=cc1,
                    thumb=thumb or None
                )
                success += 1
            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
            except Exception as e:
                errors.append(f"⚠️ Upload failed: {college} - {str(e)}")
            
            # Clean up
            if os.path.exists(filename):
                os.remove(filename)
    
    finally:
        # Final cleanup
        if thumb and os.path.exists(thumb):
            os.remove(thumb)
            
        if os.path.exists(path):
            for file in os.listdir(path):
                os.remove(os.path.join(path, file))
            os.rmdir(path)
        
        # Send report
        report = (
            f"✅ **Process Completed!**\n\n"
            f"• Success: **{success}** files\n"
            f"• Errors: **{len(errors)}** files\n"
            f"• Total Processed: **{len(links)}** files"
        )
        
        if errors:
            error_log = "\n".join(errors[:5])
            if len(errors) > 5:
                error_log += f"\n\n...and {len(errors)-5} more"
            report += f"\n\n**Errors:**\n{error_log}"
        
        await bot.send_message(chat_id, report)

async def health_check(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    print("Health check server running at http://0.0.0.0:8000/health")

async def main():
    os.makedirs("./downloads", exist_ok=True)
    print("Starting PDF Download Bot...")
    await bot.start()
    await start_web_server()
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        if bot.is_connected:
            loop.run_until_complete(bot.stop())
        loop.close()

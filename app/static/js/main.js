// 页面加载完成后执行
document.addEventListener('DOMContentLoaded', function() {
    const hostname = window.location.hostname;
    document.getElementById('remote-control').href = `http://${hostname}:8081`;
    document.getElementById('plan-manager').href = `http://${hostname}:8082`;
    
    // 切换地图按钮
    const switchMapButtons = document.querySelectorAll('.switch-map');
    switchMapButtons.forEach(button => {
        button.addEventListener('click', function() {
            const mapName = this.getAttribute('data-map');
            switchMap(mapName);
        });
    });
    
    // 建图按钮
    const startMappingBtn = document.querySelector('.start-mapping');
    if (startMappingBtn) {
        startMappingBtn.addEventListener('click', startMapping);
    }
    
    const stopMappingBtn = document.querySelector('.stop-mapping');
    if (stopMappingBtn) {
        stopMappingBtn.addEventListener('click', stopMapping);
    }
    
    const restartMappingBtn = document.querySelector('.restart-mapping');
    if (restartMappingBtn) {
        restartMappingBtn.addEventListener('click', restartMapping);
    }
    
    const saveMapBtn = document.querySelector('.save-map');
    if (saveMapBtn) {
        saveMapBtn.addEventListener('click', saveMapFile);
    }
    
    // 导航按钮
    const startNavigationBtn = document.querySelector('.start-navigation');
    if (startNavigationBtn) {
        startNavigationBtn.addEventListener('click', startNavigation);
    }
    
    const stopNavigationBtn = document.querySelector('.stop-navigation');
    if (stopNavigationBtn) {
        stopNavigationBtn.addEventListener('click', stopNavigation);
    }
    
    const restartNavigationBtn = document.querySelector('.restart-navigation');
    if (restartNavigationBtn) {
        restartNavigationBtn.addEventListener('click', restartNavigation);
    }
    
    // 新建地图功能
    const createMapBtn = document.querySelector('.create-map');
    const createMapDialog = document.getElementById('create-map-dialog');
    const closeDialogBtn = document.querySelector('.close-dialog');
    const confirmCreateMapBtn = document.getElementById('confirm-create-map');
    const cancelCreateMapBtn = document.getElementById('cancel-create-map');
    const mapNameInput = document.getElementById('map-name');
    
    // 打开新建地图对话框
    if (createMapBtn) {
        createMapBtn.addEventListener('click', function() {
            createMapDialog.style.display = 'block';
            mapNameInput.value = '';
            mapNameInput.focus();
        });
    }
    
    // 关闭对话框的多种方式
    if (closeDialogBtn) {
        closeDialogBtn.addEventListener('click', function() {
            createMapDialog.style.display = 'none';
        });
    }
    
    if (cancelCreateMapBtn) {
        cancelCreateMapBtn.addEventListener('click', function() {
            createMapDialog.style.display = 'none';
        });
    }
    
    // 点击对话框外部关闭
    window.addEventListener('click', function(event) {
        if (event.target == createMapDialog) {
            createMapDialog.style.display = 'none';
        }
    });
    
    // 确认创建新地图
    if (confirmCreateMapBtn) {
        confirmCreateMapBtn.addEventListener('click', function() {
            const mapName = mapNameInput.value.trim();
            if (mapName) {
                createNewMap(mapName);
                createMapDialog.style.display = 'none';
            } else {
                showMessage('请输入地图名称', false);
            }
        });
    }
    
    // 回车键提交
    if (mapNameInput) {
        mapNameInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const mapName = mapNameInput.value.trim();
                if (mapName) {
                    createNewMap(mapName);
                    createMapDialog.style.display = 'none';
                } else {
                    showMessage('请输入地图名称', false);
                }
            }
        });
    }
    
    // 删除地图按钮
    const deleteMapButtons = document.querySelectorAll('.delete-map');
    deleteMapButtons.forEach(button => {
        button.addEventListener('click', function() {
            const mapName = this.getAttribute('data-map');
            if (confirm(`确定要删除地图 "${mapName}" 吗？此操作不可恢复！`)) {
                deleteMap(mapName);
            }
        });
    });

    document.getElementById('remote-control').addEventListener('click', function(e) {
        e.preventDefault();
        // Android 平板/手机部分浏览器 window.open 只能用于用户点击事件
        window.open(this.href, '_blank');
    });

    document.getElementById('plan-manager').addEventListener('click', function(e) {
        e.preventDefault();
        // Android 平板/手机部分浏览器 window.open 只能用于用户点击事件
        window.open(this.href, '_blank');
    });
});

// 显示消息提示
function showMessage(message, isSuccess = true) {
    const messageBox = document.getElementById('message-box');
    const messageContent = messageBox.querySelector('.message-content');
    
    messageContent.textContent = message;
    messageBox.className = 'message-box ' + (isSuccess ? 'success' : 'error');
    messageBox.style.display = 'block';
    
    setTimeout(function() {
        messageBox.style.display = 'none';
    }, 3000);
}

// 创建新地图
function createNewMap(mapName) {
    const formData = new FormData();
    formData.append('map_name', mapName);
    
    fetch('/create_map', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        showMessage(data.message, data.success);
        if (data.success) {
            // 刷新页面以更新状态
            setTimeout(function() {
                location.reload();
            }, 1000);
        }
    })
    .catch(error => {
        showMessage('请求失败: ' + error, false);
    });
}

// 切换地图
function switchMap(mapName) {
    const formData = new FormData();
    formData.append('map_name', mapName);
    
    fetch('/switch_map', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        showMessage(data.message, data.success);
        if (data.success) {
            // 刷新页面以更新状态
            setTimeout(function() {
                location.reload();
            }, 1000);
        }
    })
    .catch(error => {
        showMessage('请求失败: ' + error, false);
    });
}

// 启动建图
function startMapping() {
    fetch('/start_mapping', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        showMessage(data.message, data.success);
        //if (data.success) {
            // 刷新页面以更新状态
            setTimeout(function() {
                location.reload();
            }, 1000);
        //}
    })
    .catch(error => {
        showMessage('请求失败: ' + error, false);
    });
}

// 停止建图
function stopMapping() {
    fetch('/stop_mapping', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        showMessage(data.message, data.success);
        //if (data.success) {
            // 刷新页面以更新状态
            setTimeout(function() {
                location.reload();
            }, 1000);
        //}
    })
    .catch(error => {
        showMessage('请求失败: ' + error, false);
    });
}

// 保存地图
function saveMapFile() {
    fetch('/save_map_file', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        showMessage(data.message, data.success);
        if (data.success) {
            // 刷新页面以更新状态
            setTimeout(function() {
                location.reload();
            }, 1000);
        }
    })
    .catch(error => {
        showMessage('请求失败: ' + error, false);
    });
}

// 启动导航
function startNavigation() {
    fetch('/start_navigation', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        showMessage(data.message, data.success);
        //if (data.success) {
            // 刷新页面以更新状态
            setTimeout(function() {
                location.reload();
            }, 1000);
        //}
    })
    .catch(error => {
        showMessage('请求失败: ' + error, false);
    });
}

// 停止导航
function stopNavigation() {
    fetch('/stop_navigation', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        showMessage(data.message, data.success);
        //if (data.success) {
            // 刷新页面以更新状态
            setTimeout(function() {
                location.reload();
            }, 1000);
        //}
    })
    .catch(error => {
        showMessage('请求失败: ' + error, false);
    });
}

// 删除地图
function deleteMap(mapName) {
    const formData = new FormData();
    formData.append('map_name', mapName);
    
    fetch('/delete_map', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        showMessage(data.message, data.success);
        if (data.success) {
            // 刷新页面以更新状态
            setTimeout(function() {
                location.reload();
            }, 1000);
        }
    })
    .catch(error => {
        showMessage('请求失败: ' + error, false);
    });
}
